// Evaluate the CEL expressions in a rendered Rezono admission release.
// The offline apiserver oracle separately exercises Kubernetes matching and enforcement.
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"slices"
	"strings"
)

const (
	reviewVersion = "admission.k8s.io/v1"
	policyVersion = "admissionregistration.k8s.io/v1"
)

type resource struct {
	APIVersion string
	Kind       string
	Metadata   struct {
		Name      string
		Namespace string
		Labels    map[string]string
	}
	Spec json.RawMessage
	Raw  json.RawMessage `json:"-"`
}

type admissionReview struct {
	APIVersion string
	Kind       string
	Request    json.RawMessage
}

type admissionRequest struct {
	UID         string
	Operation   string
	Namespace   string
	SubResource string
	Resource    struct {
		Group    string
		Version  string
		Resource string
	}
}

type admissionResponse struct {
	UID     string  `json:"uid"`
	Allowed bool    `json:"allowed"`
	Status  *status `json:"status,omitempty"`
}

type status struct {
	Message string `json:"message"`
}

type admissionResult struct {
	APIVersion string            `json:"apiVersion"`
	Kind       string            `json:"kind"`
	Response   admissionResponse `json:"response"`
}

type resourceRule struct {
	APIGroups   []string
	APIVersions []string
	Operations  []string
	Resources   []string
	Scope       string
}

func (r resourceRule) matches(req admissionRequest) bool {
	name := req.Resource.Resource
	if req.SubResource != "" {
		name += "/" + req.SubResource
	}
	return (r.Scope == "" || r.Scope == "Namespaced") &&
		slices.Contains(r.APIGroups, req.Resource.Group) &&
		slices.Contains(r.APIVersions, req.Resource.Version) &&
		slices.Contains(r.Operations, req.Operation) &&
		slices.Contains(r.Resources, name)
}

type bindingSpec struct {
	PolicyName        string
	ValidationActions []string
	ParamRef          struct {
		Name                    string
		Namespace               string
		ParameterNotFoundAction string
	}
	MatchResources struct {
		NamespaceSelector struct {
			MatchLabels map[string]string
		}
	}
}

type policySpec struct {
	FailurePolicy string
	ParamKind     struct {
		APIVersion string
		Kind       string
	}
	MatchConstraints struct {
		ResourceRules []resourceRule
	}
	Variables []struct {
		Name       string
		Expression string
	}
	Validations []struct {
		Expression string
		Message    string
	}
}

func decodeSpec[T any](spec json.RawMessage) (T, error) {
	var result T
	decoder := json.NewDecoder(bytes.NewReader(spec))
	// Fail the probe if the release uses matching features this harness does not model.
	decoder.DisallowUnknownFields()
	err := decoder.Decode(&result)
	return result, err
}

func readRelease(path string) ([]resource, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var list struct {
		APIVersion string
		Kind       string
		Items      []json.RawMessage
	}
	if err := json.Unmarshal(data, &list); err != nil {
		return nil, err
	}
	if list.APIVersion != "v1" || list.Kind != "List" || len(list.Items) == 0 {
		return nil, errors.New("expected a nonempty v1 release List")
	}
	result := make([]resource, 0, len(list.Items))
	seen := make(map[[4]string]bool)
	for _, raw := range list.Items {
		var item resource
		if err := json.Unmarshal(raw, &item); err != nil {
			return nil, err
		}
		key := [4]string{item.APIVersion, item.Kind, item.Metadata.Namespace, item.Metadata.Name}
		if item.APIVersion == "" || item.Kind == "" || item.Metadata.Name == "" || seen[key] {
			return nil, fmt.Errorf("invalid or duplicate release resource %q", key)
		}
		seen[key] = true
		item.Raw = raw
		result = append(result, item)
	}
	return result, nil
}

func lookup(items []resource, version, kind, namespace, name string) *resource {
	for i := range items {
		item := &items[i]
		if item.APIVersion == version && item.Kind == kind &&
			item.Metadata.Namespace == namespace && item.Metadata.Name == name {
			return item
		}
	}
	return nil
}

func matchesLabels(labels, selector map[string]string) bool {
	for key, want := range selector {
		if got, ok := labels[key]; !ok || got != want {
			return false
		}
	}
	return true
}

func validateRelease(items []resource, req admissionRequest, raw json.RawMessage) (string, error) {
	namespace := lookup(items, "v1", "Namespace", "", req.Namespace)
	if namespace == nil {
		return "", fmt.Errorf("namespace %q is absent from the release", req.Namespace)
	}
	expressions, err := newEvaluator(raw, namespace.Raw)
	if err != nil {
		return "", err
	}
	for _, item := range items {
		if item.APIVersion != policyVersion || item.Kind != "ValidatingAdmissionPolicyBinding" {
			continue
		}
		binding, err := decodeSpec[bindingSpec](item.Spec)
		if err != nil {
			return "", fmt.Errorf("binding %q: %w", item.Metadata.Name, err)
		}
		if !matchesLabels(namespace.Metadata.Labels, binding.MatchResources.NamespaceSelector.MatchLabels) {
			continue
		}
		policy := lookup(items, policyVersion, "ValidatingAdmissionPolicy", "", binding.PolicyName)
		if policy == nil {
			return "", fmt.Errorf("binding %q has no release policy", item.Metadata.Name)
		}
		spec, err := decodeSpec[policySpec](policy.Spec)
		if err != nil {
			return "", fmt.Errorf("policy %q: %w", policy.Metadata.Name, err)
		}
		rules := spec.MatchConstraints.ResourceRules
		if len(rules) == 0 {
			return "", fmt.Errorf("policy %q has no resource rules", policy.Metadata.Name)
		}
		matched := false
		for _, rule := range rules {
			if rule.Scope != "" && rule.Scope != "Namespaced" && rule.Scope != "Cluster" {
				return "", fmt.Errorf("policy %q uses an unsupported resource scope", policy.Metadata.Name)
			}
			for _, fields := range [][]string{rule.APIGroups, rule.APIVersions, rule.Operations, rule.Resources} {
				if len(fields) == 0 || slices.ContainsFunc(fields, func(field string) bool {
					return strings.Contains(field, "*")
				}) {
					return "", fmt.Errorf("policy %q needs explicit resource matches", policy.Metadata.Name)
				}
			}
			matched = matched || rule.matches(req)
		}
		if !matched {
			continue
		}
		if !slices.Equal(binding.ValidationActions, []string{"Deny"}) ||
			spec.FailurePolicy != "Fail" || binding.ParamRef.Name == "" ||
			binding.ParamRef.ParameterNotFoundAction != "Deny" || len(spec.Validations) == 0 {
			return "", fmt.Errorf("unsupported release policy or binding %q", item.Metadata.Name)
		}
		paramNamespace := binding.ParamRef.Namespace
		if paramNamespace == "" {
			paramNamespace = req.Namespace
		}
		param := lookup(items, spec.ParamKind.APIVersion, spec.ParamKind.Kind, paramNamespace, binding.ParamRef.Name)
		if param == nil {
			return fmt.Sprintf("%s: publication parameter %q not found", policy.Metadata.Name, binding.ParamRef.Name), nil
		}
		msg, err := expressions.validate(spec, param.Raw)
		if err != nil {
			return fmt.Sprintf("%s: %v", policy.Metadata.Name, err), nil
		}
		if msg != "" {
			return msg, nil
		}
	}
	return "", nil
}

func run(path string, in io.Reader, out io.Writer) error {
	if path == "" {
		return errors.New("--release is required")
	}
	items, err := readRelease(path)
	if err != nil {
		return err
	}
	var review admissionReview
	if err := json.NewDecoder(in).Decode(&review); err != nil {
		return err
	}
	var request admissionRequest
	if err := json.Unmarshal(review.Request, &request); err != nil {
		return err
	}
	if review.APIVersion != reviewVersion || review.Kind != "AdmissionReview" ||
		request.UID == "" || request.Operation == "" || request.Namespace == "" ||
		request.Resource.Version == "" || request.Resource.Resource == "" {
		return errors.New("expected a namespaced v1 AdmissionReview request")
	}
	msg, err := validateRelease(items, request, review.Request)
	if err != nil {
		return err
	}
	response := admissionResponse{UID: request.UID, Allowed: msg == ""}
	if msg != "" {
		response.Status = &status{Message: msg}
	}
	return json.NewEncoder(out).Encode(admissionResult{
		APIVersion: reviewVersion, Kind: "AdmissionReview", Response: response,
	})
}

func main() {
	release := flag.String("release", "", "path to the rendered release List")
	flag.Parse()
	if err := run(*release, os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
