# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS binary

ARG TARGETARCH

# These are the SHA-256 digests published with the exact upstream release.
# They are repository pins, not checksums fetched during the build.
RUN python - <<'PY'
import hashlib
import os
import urllib.request
from pathlib import Path

release = "RELEASE.2025-09-07T16-13-09Z"
expected = {
    "amd64": "7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f",
    "arm64": "5c83cd2cf151717ba0243f73e1c7802ff36e272b67144bdd7f1f7d684fd6f03d",
}
arch = os.environ["TARGETARCH"]
if arch not in expected:
    raise SystemExit(f"Unsupported MinIO target architecture: {arch}")
url = (
    "https://github.com/minio/minio/releases/download/"
    f"{release}/minio.linux-{arch}.{release}"
)
request = urllib.request.Request(url, headers={"User-Agent": "BusinessOS-CI"})
binary = Path("/opt/minio")
digest = hashlib.sha256()
with urllib.request.urlopen(request, timeout=60) as source, binary.open("wb") as target:
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
        target.write(chunk)
actual = digest.hexdigest()
if actual != expected[arch]:
    raise SystemExit(f"MinIO binary checksum mismatch: {actual}")
binary.chmod(0o755)
print(f"Verified MinIO {release} linux/{arch}: sha256:{actual}")
PY

FROM scratch
COPY --from=binary /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=binary /opt/minio /usr/local/bin/minio
WORKDIR /tmp
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
