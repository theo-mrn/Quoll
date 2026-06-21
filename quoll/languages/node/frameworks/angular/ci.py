from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from quoll.ci.steps import Item, step
from quoll.languages.base import FrameworkCI

if TYPE_CHECKING:
    from quoll.ci.config import CIConfig

# Karma drives a real Chrome. Runners have one; Node images don't: install Chromium, through a launcher adding
# --no-sandbox (container jobs run as root, where Chrome's sandbox can't start).
_CHROME = """if [ -z "${CHROME_BIN:-}" ] && ! command -v google-chrome >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq --no-install-recommends chromium >/dev/null
  printf '#!/bin/sh\\nexec chromium --no-sandbox "$@"\\n' > /usr/local/bin/chromium-ci
  chmod +x /usr/local/bin/chromium-ci
  echo "CHROME_BIN=/usr/local/bin/chromium-ci" >> "${GITHUB_ENV:-/dev/null}"
fi"""


class AngularCI(FrameworkCI):
    def env(self, cfg: CIConfig) -> Dict[str, str]:
        return {"NG_CLI_ANALYTICS": "false"}

    def test(self, cfg: CIConfig) -> List[Item]:
        ci = cfg.language.ci
        cmd = ci.exec(cfg, "ng test --watch=false")
        steps: List[Item] = list(ci.install(cfg))
        if cfg.test.runner == "angular-karma":
            cmd += " --browsers=ChromeHeadless"
            steps.append(step("Chrome for Karma", run=_CHROME))
            # Same shell on container platforms: the launcher installed above, if any.
            cmd = f'if [ -x /usr/local/bin/chromium-ci ]; then export CHROME_BIN=/usr/local/bin/chromium-ci; fi\n{cmd}'
        return [*steps, step("Tests", run=cmd, secrets=cfg.test.env_secrets)]
