// Run the upstream admission plugin against a release in memory.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	admissionv1 "k8s.io/api/admission/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/runtime/serializer"
	"k8s.io/apiserver/pkg/admission"
	"k8s.io/apiserver/pkg/admission/plugin/policy/matching"
	"k8s.io/apiserver/pkg/admission/plugin/policy/validating"
	"k8s.io/apiserver/pkg/authentication/user"
	"k8s.io/apiserver/pkg/authorization/authorizer"
	dynamicfake "k8s.io/client-go/dynamic/fake"
	"k8s.io/client-go/informers"
	clientfake "k8s.io/client-go/kubernetes/fake"
)

func evaluator(ctx context.Context, bundle *release) (*validating.Plugin, error) {
	client := clientfake.NewSimpleClientset(bundle.objects...)
	parameters := dynamicfake.NewSimpleDynamicClientWithCustomListKinds(
		runtime.NewScheme(), bundle.listKinds, bundle.parameters...,
	)
	factory := informers.NewSharedInformerFactory(client, 0)
	namespaces := factory.Core().V1().Namespaces()
	plugin := validating.NewPlugin(nil)
	plugin.SetEnabled(true)
	plugin.SetExternalKubeClientSet(client)
	plugin.SetExternalKubeInformerFactory(factory)
	plugin.SetDynamicClient(parameters)
	plugin.SetRESTMapper(bundle.mapper)
	plugin.SetDrainedNotification(ctx.Done())
	plugin.SetMatcher(matching.NewMatcher(namespaces.Lister(), client))
	plugin.SetAuthorizer(authorizer.AuthorizerFunc(func(context.Context, authorizer.Attributes) (authorizer.Decision, string, error) {
		return authorizer.DecisionDeny, "no external authorization in the offline oracle", nil
	}))
	if err := plugin.ValidateInitialization(); err != nil {
		return nil, err
	}
	factory.Start(ctx.Done())
	if !plugin.WaitForReady() {
		return nil, fmt.Errorf("admission policy informers did not become ready")
	}
	return plugin, nil
}

func attributes(req *admissionv1.AdmissionRequest, scheme *runtime.Scheme) (admission.Attributes, error) {
	decode := serializer.NewCodecFactory(scheme, serializer.EnableStrict).UniversalDeserializer()
	decodeObject := func(raw runtime.RawExtension) (runtime.Object, error) {
		if len(raw.Raw) == 0 || string(raw.Raw) == "null" {
			return nil, nil
		}
		return runtime.Decode(decode, raw.Raw)
	}
	newObject, err := decodeObject(req.Object)
	if err != nil {
		return nil, err
	}
	oldObject, err := decodeObject(req.OldObject)
	if err != nil {
		return nil, err
	}
	var options runtime.Object
	if len(req.Options.Raw) > 0 && string(req.Options.Raw) != "null" {
		options, err = decodeObject(req.Options)
		if err != nil {
			return nil, err
		}
	}
	operation := admission.Operation(req.Operation)
	switch operation {
	case admission.Create, admission.Update, admission.Delete, admission.Connect:
	default:
		return nil, fmt.Errorf("unknown admission operation %q", operation)
	}
	identity := &user.DefaultInfo{
		Name:   req.UserInfo.Username,
		UID:    req.UserInfo.UID,
		Groups: req.UserInfo.Groups,
		Extra:  map[string][]string{},
	}
	for key, value := range req.UserInfo.Extra {
		identity.Extra[key] = value
	}
	dryRun := req.DryRun != nil && *req.DryRun
	return admission.NewAttributesRecord(newObject, oldObject, schema.GroupVersionKind(req.Kind),
		req.Namespace, req.Name, schema.GroupVersionResource(req.Resource), req.SubResource,
		operation, options, dryRun, identity), nil
}

func evaluate(bundle *release, request *admissionv1.AdmissionRequest) (*admissionv1.AdmissionResponse, error) {
	scheme := runtime.NewScheme()
	if err := corev1.AddToScheme(scheme); err != nil {
		return nil, err
	}
	if err := networkingv1.AddToScheme(scheme); err != nil {
		return nil, err
	}
	attr, err := attributes(request, scheme)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	plugin, err := evaluator(ctx, bundle)
	if err != nil {
		return nil, err
	}
	response := &admissionv1.AdmissionResponse{UID: request.UID, Allowed: true}
	if err := plugin.Validate(ctx, attr, admission.NewObjectInterfacesFromScheme(scheme)); err != nil {
		var apiStatus apierrors.APIStatus
		if !errors.As(err, &apiStatus) {
			return nil, err
		}
		status := apiStatus.Status()
		response.Allowed = false
		response.Result = &status
	}
	return response, nil
}

func run(path string, input io.Reader, output io.Writer) error {
	if path == "" {
		return fmt.Errorf("--release is required")
	}
	bundle, err := parseRelease(path)
	if err != nil {
		return err
	}
	var review admissionv1.AdmissionReview
	if err := json.NewDecoder(input).Decode(&review); err != nil {
		return err
	}
	if review.APIVersion != admissionv1.SchemeGroupVersion.String() || review.Kind != "AdmissionReview" || review.Request == nil {
		return fmt.Errorf("expected an admission.k8s.io/v1 AdmissionReview request")
	}
	response, err := evaluate(bundle, review.Request)
	if err != nil {
		return err
	}
	return json.NewEncoder(output).Encode(admissionv1.AdmissionReview{TypeMeta: metav1.TypeMeta{
		APIVersion: review.APIVersion,
		Kind:       review.Kind,
	}, Response: response})
}

func main() {
	path := flag.String("release", "", "Kubernetes release List in JSON")
	flag.Parse()
	if err := run(*path, os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
