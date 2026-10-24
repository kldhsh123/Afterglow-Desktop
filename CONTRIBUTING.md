# Contributing to Afterglow Desktop

[简体中文](README/CONTRIBUTING.zh-CN.md) · [README](README.md)

Bug reports, documentation, translations, and code contributions are welcome. Please search existing issues before opening a new one. Discuss large changes in an issue first.

## Working on the code

1. Fork this repository and create a branch from the current default branch.
2. Install Node.js/npm, Python 3.12, and Rust/Tauri prerequisites for native desktop work.
3. Run `npm ci`, then `npm run dev` for a browser preview.
4. Keep changes focused and add tests for changed behavior where practical.
5. Open a PR against this repository's default branch and describe the change and the checks you actually ran.

The UI uses Vue 3 and TypeScript; native integration uses Tauri 2 and Rust; `desktop_host/` contains the Python host and bundled extensions. Keep visible strings in `locales/en-US.json` and `locales/zh-CN.json`, and update both installer language files when changing installer text.

Full desktop development needs verified Windows x64 Python/core resources. Read `python3 scripts/prepare_windows.py --help` before preparing them. Generated resources are not committed. The runtime core is sourced from [kldhsh123/Afterglow](https://github.com/kldhsh123/Afterglow); preserve its notices and keep desktop-specific changes distinct from upstream code.

## Checks

Run checks relevant to your changes and report any that you could not run:

```bash
npm test
npx vue-tsc --noEmit
python3 -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

Installer or tray changes also need manual verification on Windows. State that explicitly if it has not been done. Do not include build output in a PR. `version.json` is the version source. Releases now use stable versions: maintainers run `npm run version:bump` once to advance the patch version (for example, `0.1.0` → `0.1.1`) and synchronize npm, Cargo, Tauri, and runtime catalogs. The command also advances the Windows build counter automatically. To synchronize the current version without increasing it, use `npm run version:sync`. Neither command builds the application. For a minor or major release, maintainers edit `baseVersion` explicitly and synchronize it.

## Reports and repository hygiene

- Use the issue templates for bugs and feature requests. Include desktop/core versions and your Windows version when reporting a bug.
- Remove API keys, tokens, personal information, and private chat content from logs and screenshots. Use synthetic data for examples and test fixtures.
- Do not commit `.env` files, local configuration, chat exports, logs, development caches, dependencies, generated schemas, or release binaries.
- Preserve copyright and license notices. List added dependencies and their licenses in your PR when applicable.
- For a bug in the upstream core, link the relevant [Afterglow issue](https://github.com/kldhsh123/Afterglow/issues) rather than copying its implementation into the desktop UI.

## Contribution agreement and code ownership

Submitting a Pull Request constitutes agreement to all terms in this section. Please read them carefully.

By submitting a Pull Request (PR) to this repository or otherwise contributing code, you agree to the following terms:

1. You retain copyright in your own contributions.
2. You grant the repository owner (kldhsh123 and their designated successors/assignees) a perpetual, irrevocable, non-exclusive, worldwide, royalty-free right to use, copy, modify, merge, publish, distribute, sublicense, and relicense your contributions in any form, including incorporating them into the project as a whole and changing the license of the entire project.
3. This grant applies to any current or future license.
4. Your contributions are distributed by default under the project's current license (AGPL-3.0), but the repository owner may change the license of the entire project at any time without obtaining further consent from you.
5. If you impose additional restrictions on a particular contribution, state them explicitly in the PR description; otherwise, the grant is deemed unrestricted.
6. These terms form part of the Contributor License Agreement (CLA).

This arrangement is intended to let Afterglow-Desktop develop flexibly over the long term while respecting each contributor's work.

You may grant only rights you hold or are authorized to grant. Identify third-party code and its origin in your PR. This agreement does not override the copyright or license of Afterglow core, dependencies, or any other third-party material, and does not grant rights on behalf of their authors.
