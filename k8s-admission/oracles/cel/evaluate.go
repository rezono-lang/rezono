package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/cel-go/cel"
)

type evaluator struct {
	env     *cel.Env
	request map[string]any
	ns      map[string]any
}

func newEvaluator(request, namespace json.RawMessage) (*evaluator, error) {
	wire := cel.MapType(cel.StringType, cel.DynType)
	env, err := cel.NewEnv(
		cel.Variable("request", wire),
		cel.Variable("object", wire),
		cel.Variable("oldObject", wire),
		cel.Variable("namespaceObject", wire),
		cel.Variable("params", wire),
		cel.Variable("variables", wire),
	)
	if err != nil {
		return nil, err
	}
	req, err := valueMap(request)
	if err != nil {
		return nil, err
	}
	ns, err := valueMap(namespace)
	if err != nil {
		return nil, err
	}
	return &evaluator{env: env, request: req, ns: ns}, nil
}

func valueMap(raw json.RawMessage) (map[string]any, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var data map[string]any
	if err := decoder.Decode(&data); err != nil {
		return nil, err
	}
	_, err := convertNumbers(data)
	return data, err
}

// Keep integer fields typed as CEL ints, including NetworkPolicy ports.
func convertNumbers(raw any) (any, error) {
	switch value := raw.(type) {
	case json.Number:
		literal := value.String()
		if strings.ContainsAny(literal, ".eE") {
			return strconv.ParseFloat(literal, 64)
		}
		return value.Int64()
	case []any:
		for i, item := range value {
			converted, err := convertNumbers(item)
			if err != nil {
				return nil, err
			}
			value[i] = converted
		}
	case map[string]any:
		for key, item := range value {
			converted, err := convertNumbers(item)
			if err != nil {
				return nil, err
			}
			value[key] = converted
		}
	}
	return raw, nil
}

func (e *evaluator) eval(source string, bindings map[string]any) (any, error) {
	ast, problems := e.env.Compile(source)
	if problems.Err() != nil {
		return nil, problems.Err()
	}
	program, err := e.env.Program(ast)
	if err != nil {
		return nil, err
	}
	result, _, err := program.Eval(bindings)
	if err != nil {
		return nil, err
	}
	return result.Value(), nil
}

func (e *evaluator) validate(policy policySpec, param json.RawMessage) (string, error) {
	params, err := valueMap(param)
	if err != nil {
		return "", err
	}
	variables := make(map[string]any)
	bindings := map[string]any{
		"request": e.request, "object": e.request["object"], "oldObject": e.request["oldObject"],
		"namespaceObject": e.ns, "params": params, "variables": variables,
	}
	for _, variable := range policy.Variables {
		value, err := e.eval(variable.Expression, bindings)
		if err != nil {
			return "", fmt.Errorf("evaluate variable %q: %w", variable.Name, err)
		}
		variables[variable.Name] = value
	}
	for _, validation := range policy.Validations {
		value, err := e.eval(validation.Expression, bindings)
		if err != nil {
			return "", err
		}
		passed, ok := value.(bool)
		if !ok {
			return "", fmt.Errorf("validation returned %T instead of bool", value)
		}
		if !passed {
			if validation.Message == "" {
				return "", fmt.Errorf("validation failed")
			}
			return validation.Message, nil
		}
	}
	return "", nil
}
