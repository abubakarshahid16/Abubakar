#!/usr/bin/env bash
# Install the repository's git hooks and the gitleaks binary they depend on.
#
# Run once after cloning:  bash scripts/install-git-hooks.sh

set -euo pipefail

GITLEAKS_VERSION="8.30.1"
GITLEAKS_SHA256_WINDOWS="d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e"
GITLEAKS_SHA256_LINUX="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"

echo "==> Pointing git at .githooks/"
git config --local core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    DEST="${LOCALAPPDATA}/gitleaks"; BIN="$DEST/gitleaks.exe"
    ASSET="gitleaks_${GITLEAKS_VERSION}_windows_x64.zip"; SUM="$GITLEAKS_SHA256_WINDOWS" ;;
  *)
    DEST="$HOME/.local/bin"; BIN="$DEST/gitleaks"
    ASSET="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"; SUM="$GITLEAKS_SHA256_LINUX" ;;
esac

if [ -x "$BIN" ]; then
  echo "==> gitleaks already installed: $("$BIN" version)"
else
  echo "==> Downloading gitleaks ${GITLEAKS_VERSION}"
  mkdir -p "$DEST"
  curl -sSfL -o "$DEST/$ASSET" \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${ASSET}"

  echo "==> Verifying SHA-256"
  echo "${SUM}  ${DEST}/${ASSET}" | sha256sum -c -

  case "$ASSET" in
    *.zip) unzip -o -q "$DEST/$ASSET" -d "$DEST" gitleaks.exe ;;
    *.tar.gz) tar -xzf "$DEST/$ASSET" -C "$DEST" gitleaks ;;
  esac
  rm -f "$DEST/$ASSET"
  chmod +x "$BIN"
  echo "==> Installed: $("$BIN" version)"
fi

echo ""
echo "Done. Hooks active at .githooks/ (core.hooksPath)."
echo "Verify with:  git config --local core.hooksPath"
