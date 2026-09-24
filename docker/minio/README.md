# MinIO development and CI image

This image packages the unmodified MinIO Community binary for
`RELEASE.2025-09-07T16-13-09Z` for ephemeral development and CI object storage.
MinIO identifies this release as GNU AGPLv3. See the
[upstream license](https://github.com/minio/minio/blob/RELEASE.2025-09-07T16-13-09Z/LICENSE)
and [release](https://github.com/minio/minio/releases/tag/RELEASE.2025-09-07T16-13-09Z).
No MinIO source or binary modification is made here.

The former Quay image stopped granting anonymous pull access. The original
`dl.min.io` archive URLs for this release return HTTP 410, so the build uses
the same official `minio/minio` GitHub release assets. The Dockerfile pins
the binary SHA-256 values independently of the download location:

| Architecture | SHA-256 |
| --- | --- |
| `linux/amd64` | `7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f` |
| `linux/arm64` | `5c83cd2cf151717ba0243f73e1c7802ff36e272b67144bdd7f1f7d684fd6f03d` |

Both values match the upstream `.sha256sum` assets and the digests displayed
for the binaries on the upstream release page. Both binary downloads were
independently hashed before these values were committed. Upstream `.asc` and
`.minisig` assets are also published for both architectures; this build uses
the repository-pinned SHA-256 values as its fail-closed identity check.

The builder reuses BusinessOS's existing digest-pinned Python image. The
runtime image starts from `scratch` and contains only the MinIO binary and CA
certificate bundle. The S3 endpoint, credentials, ports, volume, and command
remain defined by `compose.yaml`.
