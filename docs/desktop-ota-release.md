# Desktop signed OTA releases

Release builds keep the complete frozen Python backend, FFmpeg/FFprobe, diarization
models and official lark-cli. The Tauri v2 updater replaces this complete desktop
package. Windows uses the NSIS `.exe` and `.exe.sig`; macOS uses `.app.tar.gz`
and `.app.tar.gz.sig` for OTA and retains the `.dmg` for manual installation.

The stable endpoint is
`https://github.com/vilab-orulink/Vinote-public/releases/latest/download/latest.json`.
Test packages explicitly disable updater artifact creation and have no stable
endpoint. Stable packaging refuses to proceed without a signing private key and
configured public key. The private key/password never belong in source control,
the installer, or release metadata. Back up the signing key securely: replacing
it prevents existing installations from verifying future updates.

1. Commit the intended source changes. Set `TAURI_SIGNING_PRIVATE_KEY` (Tauri key
   text or its supported key-file path) and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
   as needed. The public key is read automatically from
   `config/desktop-updater-public.json`; `VINOTE_UPDATER_PUBLIC_KEY` can override
   it with the matching public key text during packaging.
2. Run `node scripts/build-desktop.mjs --channel release` on each native build
   platform. Keep all generated files and `manifest.json` together in the printed
   artifact directory. Building Windows does not produce a macOS package.
3. Review the plan without GitHub writes:
   `node scripts/publish-desktop-release.mjs --plan <windows-artifact-dir> [<mac-artifact-dir>]`.
   Optional `--notes <file>` reads release notes, and `--public-key <file>` reads
   the public key. Each supplied platform must have the same version/source
   commit, already merged into the source repository's `dev` branch. A Windows-only release advertises only Windows, never an unavailable
   macOS update. The uploader rejects dirty source receipts and altered files.
4. Authenticate `gh` for both `orulink-ai/VINote` and
   `vilab-orulink/Vinote-public`, with release-write permission. The public repository
   needs an initialized default branch. Run the same command without `--plan`
   to create drafts and upload identical packages to both repositories. The
   public repo receives assets and release notes only, not the private source.
5. Add `--publish` to upload/verify and publish both releases. Existing published
   versions are immutable to this script; select a new project version instead.

The script checks SHA256 receipts and verifies minisign signatures locally,
including the trusted comment. It requires GitHub's reported SHA256 asset digest
to match every local artifact. It uploads installers/signatures and the aggregate
`manifest.json` first, then `latest.json`. Both repositories must finish upload
and verification before either release is published. Public download URLs always
refer to the exact version tag, so a later latest-release change cannot replace
an in-flight payload.

GitHub cannot atomically publish across repositories. The source release is
published first and public OTA endpoint last. If publishing the second fails,
inspect both release states; do not delete or overwrite a published version. An
operator can finish publishing the already verified public draft. Failed uploads
remain drafts and can be retried; unexpected extra draft assets cause a failure
requiring inspection. No remote assets or tags are deleted automatically.

Validation: `node --test scripts/ota-release.test.mjs`. These tests cover channel
isolation, signature interoperability/tampering, checksum/clean-source gates,
manifest URLs and dual-repository publish ordering. They do not establish an
actual installer launch or an end-to-end update on a user's device.

## Migration from the former public repository

Versions through 0.3.8 check `Ro-In-AI/Vinote-public`. This migration does not publish a bridge there: install 0.3.9 from the new public repository to switch existing installations to the new endpoint. Starting with 0.3.9, subsequent stable updates use `vilab-orulink/Vinote-public`. Keep the existing updater signing key.


## macOS archive and native-install acceptance

macOS OTA archives contain exactly one `.app` root. `scripts/macos-updater-archive.mjs` creates deferred-signing archives with `COPYFILE_DISABLE=1` and validates all release archives through the standard-library raw-tar checker. AppleDouble members such as `._VINote.app` must never reach the native updater, which strips the first path component during extraction. BSD tar may hide these members in its listing, so a successful `tar -t` or ordinary extraction is insufficient evidence. Keep the real `Contents/CodeResources` notarization ticket file. Repacking changes the archive hash and requires a new updater signature.

`node --test scripts/macos-updater-archive.test.mjs` exercises both a clean application archive and rejection of AppleDouble siblings. `VINOTE_MACOS_OTA_FIXTURE_APP` can point to a prepared App for the optional real-bundle case. These checks run in the project verification script and CI.

A signed and notarized DMG is the initial installation. Install VINote into Applications; future OTA uses the complete signed `.app.tar.gz`. Each subsequent stable release must publish a newer version with its actual `darwin-aarch64` entry, URL and matching signature at the configured stable endpoint. A lower/equal version is not an upgrade. Keep the trusted key unchanged. Native acceptance uses an isolated bundle and the exact shipped updater version to check the live feed, download and verify the public payload, install it, and verify the resulting bundle; it does not create a fake public release.

After Windows and macOS clients are both deployed, promote the next shared stable OTA release with matching-version Windows and macOS packages and both platform entries. A same-version macOS manual-install repair, such as this 0.3.11 DMG, does not promote the shared Windows 0.3.10 latest release. This keeps current clients stable until the next complete release is ready.
