package main

import (
	"encoding/json"
	"fmt"
	"os"

	admissionregistrationv1 "k8s.io/api/admissionregistration/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// Only discovery fields of a CRD are needed to map the offline parameter store.
type resourceDefinition struct {
	Spec struct {
		Group, Scope string
		Names        struct{ Kind, Singular, Plural string }
		Versions     []struct {
			Name   string
			Served bool
		}
	}
}

type release struct {
	objects    []runtime.Object
	parameters []runtime.Object
	mapper     *meta.DefaultRESTMapper
	listKinds  map[schema.GroupVersionResource]string
}

func parseRelease(path string) (*release, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var list metav1.List
	if err := json.Unmarshal(data, &list); err != nil {
		return nil, err
	}
	if list.APIVersion != "v1" || list.Kind != "List" {
		return nil, fmt.Errorf("expected a Kubernetes v1 List")
	}
	result := &release{
		mapper:    meta.NewDefaultRESTMapper(nil),
		listKinds: map[schema.GroupVersionResource]string{},
	}
	var instances []*unstructured.Unstructured
	for _, item := range list.Items {
		var header metav1.TypeMeta
		if err := json.Unmarshal(item.Raw, &header); err != nil {
			return nil, err
		}
		var object runtime.Object
		switch header.GroupVersionKind() {
		case corev1.SchemeGroupVersion.WithKind("Namespace"):
			object = &corev1.Namespace{}
		case admissionregistrationv1.SchemeGroupVersion.WithKind("ValidatingAdmissionPolicy"):
			object = &admissionregistrationv1.ValidatingAdmissionPolicy{}
		case admissionregistrationv1.SchemeGroupVersion.WithKind("ValidatingAdmissionPolicyBinding"):
			object = &admissionregistrationv1.ValidatingAdmissionPolicyBinding{}
		case schema.GroupVersion{Group: "apiextensions.k8s.io", Version: "v1"}.WithKind("CustomResourceDefinition"):
			var definition resourceDefinition
			if err := json.Unmarshal(item.Raw, &definition); err != nil {
				return nil, err
			}
			if err := result.addDefinition(definition); err != nil {
				return nil, err
			}
			continue
		default:
			var instance unstructured.Unstructured
			if err := json.Unmarshal(item.Raw, &instance); err != nil {
				return nil, err
			}
			instances = append(instances, &instance)
			continue
		}
		if err := json.Unmarshal(item.Raw, object); err != nil {
			return nil, err
		}
		result.objects = append(result.objects, object)
	}
	for _, instance := range instances {
		kind := instance.GroupVersionKind()
		mapping, err := result.mapper.RESTMapping(kind.GroupKind(), kind.Version)
		if err != nil {
			return nil, fmt.Errorf("parameter %q: %w", instance.GetName(), err)
		}
		if (mapping.Scope.Name() == meta.RESTScopeNameNamespace) != (instance.GetNamespace() != "") {
			return nil, fmt.Errorf("parameter %q does not match its resource scope", instance.GetName())
		}
		result.parameters = append(result.parameters, instance)
	}
	return result, nil
}

func (r *release) addDefinition(definition resourceDefinition) error {
	spec := definition.Spec
	var scope meta.RESTScope
	switch spec.Scope {
	case "Namespaced":
		scope = meta.RESTScopeNamespace
	case "Cluster":
		scope = meta.RESTScopeRoot
	default:
		return fmt.Errorf("invalid resource scope %q", spec.Scope)
	}
	if spec.Group == "" || spec.Names.Kind == "" || spec.Names.Plural == "" || spec.Names.Singular == "" {
		return fmt.Errorf("incomplete discovery metadata for custom resource")
	}
	for _, version := range spec.Versions {
		if !version.Served {
			continue
		}
		groupVersion := schema.GroupVersion{Group: spec.Group, Version: version.Name}
		resource := groupVersion.WithResource(spec.Names.Plural)
		kind := groupVersion.WithKind(spec.Names.Kind)
		r.mapper.AddSpecific(kind, resource, groupVersion.WithResource(spec.Names.Singular), scope)
		r.listKinds[resource] = spec.Names.Kind + "List"
	}
	return nil
}
