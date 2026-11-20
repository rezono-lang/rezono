# Pack definitions and import pins

An import in `pack.yaml` records the `sha256` of the target pack's definition. Run `python -m rezono_compiler hash <pack-directory>` to reproduce the digest from the target checkout.

- **The hash** covers `pack.yaml`, `channels.yaml`, `schema/**/*.yaml`, `rezono/**/*.rezono`, `rezono/**/*.json`, `labels/*.yaml`, `messages/*.mf2`, `rules/*.dl`, `calc/*.yaml`, `sweeps.yaml`, `questions.yaml`, `views.yaml`, `icons/*.svg`, `icons/sources.yaml` and `ports/*.yaml`.

Hash each matching file's exact bytes with SHA-256. Use its path relative to the pack root with forward slashes as the key and its lowercase hexadecimal digest as the value. Serialize this map as compact UTF-8 JSON, sorting path keys by UTF-16 code units. The pack digest is the lowercase hexadecimal SHA-256 of those JSON bytes. A byte change, including different line endings, changes the corresponding file digest.

The definition pin excludes fact and scenario data. Each imported pack's own `pack.yaml` is covered, so its recorded import pins travel with the definition. The compiler verifies those pins as it resolves the dependency chain.
