"""Read an allocatable device count using the verified Kubernetes client parser."""
import runpy
import sys


def main(parser, raw_capacity):
    count = runpy.run_path(parser)["parse_quantity"](raw_capacity)
    if not count.is_finite() or count <= 0 or count != count.to_integral_value():
        raise ValueError("expected a positive integer device count")
    print(int(count))


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except ValueError as exc:
        sys.exit(str(exc))
