// Evaluate the rendered flow validation and its variables using the CEL runtime.
// The input is a batch of checked publications and actual NetworkPolicy objects.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"

	"github.com/google/cel-go/cel"
)

type expression struct {
	Name       string
	Expression string
}

type sample struct {
	Variables   []expression
	Validations []expression
	Object      map[string]any
	Params      map[string]any
	Request     map[string]any
}

// Preserve Kubernetes integer ports; the generic JSON decoder otherwise uses doubles.
func integers(value any) (any, error) {
	switch v := value.(type) {
	case json.Number:
		return strconv.ParseInt(string(v), 10, 64)
	case map[string]any:
		for key, item := range v {
			converted, err := integers(item)
			if err != nil {
				return nil, err
			}
			v[key] = converted
		}
	case []any:
		for i, item := range v {
			converted, err := integers(item)
			if err != nil {
				return nil, err
			}
			v[i] = converted
		}
	}
	return value, nil
}

func evaluate(env *cel.Env, source string, bindings map[string]any) (bool, error) {
	ast, issues := env.Compile(source)
	if issues.Err() != nil {
		return false, issues.Err()
	}
	program, err := env.Program(ast)
	if err != nil {
		return false, err
	}
	value, _, err := program.Eval(bindings)
	if err != nil {
		return false, err
	}
	result, ok := value.Value().(bool)
	if !ok {
		return false, fmt.Errorf("expected a boolean, got %v", value.Type())
	}
	return result, nil
}

func run() error {
	obj := cel.MapType(cel.StringType, cel.DynType)
	env, err := cel.NewEnv(cel.Variable("object", obj), cel.Variable("params", obj),
		cel.Variable("request", obj),
		cel.Variable("variables", cel.MapType(cel.StringType, cel.BoolType)))
	if err != nil {
		return err
	}
	var samples []sample
	dec := json.NewDecoder(os.Stdin)
	dec.UseNumber()
	if err := dec.Decode(&samples); err != nil {
		return err
	}
	var results []bool
	for _, test := range samples {
		variables := map[string]bool{}
		request := test.Request
		if request == nil {
			request = map[string]any{}
		}
		bindings := map[string]any{"object": test.Object, "params": test.Params,
			"request": request, "variables": variables}
		if _, err := integers(bindings); err != nil {
			return err
		}
		for _, variable := range test.Variables {
			value, err := evaluate(env, variable.Expression, bindings)
			if err != nil {
				return err
			}
			variables[variable.Name] = value
		}
		allowed := true
		for _, validation := range test.Validations {
			value, err := evaluate(env, validation.Expression, bindings)
			if err != nil {
				return err
			}
			allowed = allowed && value
		}
		results = append(results, allowed)
	}
	return json.NewEncoder(os.Stdout).Encode(results)
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
