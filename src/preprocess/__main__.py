import argparse
import json

from .pipeline import run


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline API/FAQ/PDF normalization (M0-M2 MVP)')
    parser.add_argument('--input', default='data/raw')
    parser.add_argument('--output', default='data/processed')
    parser.add_argument('--manifest', help='Explicit file-relative provenance metadata JSON')
    parser.add_argument('--chunk-size', type=int, default=700)
    parser.add_argument('--overlap', type=int, default=100)
    parser.add_argument('--all-ages', action='store_true')
    parser.add_argument('--include-samples', action='store_true', help='Test use only; synthetic input is excluded by default')
    args = parser.parse_args(argv)
    try:
        report = run(args.input, args.output, manifest=args.manifest, size=args.chunk_size,
                     overlap=args.overlap, elderly_only=not args.all_ages, include_samples=args.include_samples)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
