"""Release engineering pins (M6 F1-F3).

The workflows, Dockerfile and compose file are text artifacts nothing else in
the suite executes; these assertions keep the release discipline from silently
disappearing (checksums asset, tag == source version, healthcheck, PUID/PGID).

Run with: python _test_release_engineering.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from wb_version import VERSION, verify_artifacts


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class VersionStringTests(unittest.TestCase):
    def test_source_version_strings_agree(self):
        src = read("wb_proxy.py")
        self.assertIn('"version": VERSION', src)
        self.assertIn('server_version = "Workbody-FHUB/" + VERSION', src)
        self.assertEqual(verify_artifacts(), VERSION)


class WorkflowTests(unittest.TestCase):
    def test_tests_workflow_asserts_tag_against_source(self):
        text = read(".github", "workflows", "tests.yml")
        self.assertIn('tags: ["v*"]', text)
        self.assertIn("version-assert", text)
        self.assertIn("refs/tags/v", text)
        self.assertIn("GITHUB_REF_NAME", text)
        self.assertIn("verify_artifacts", text)

    def test_release_checksums_workflow_hashes_every_asset(self):
        text = read(".github", "workflows", "release-checksums.yml")
        self.assertIn("types: [published]", text)
        self.assertIn("gh release download", text)
        self.assertIn("sha256sum *", text)
        self.assertIn("gh release upload", text)
        self.assertIn("checksums.txt", text)


class DockerTests(unittest.TestCase):
    def test_healthcheck_probes_the_health_endpoint(self):
        text = read("Dockerfile")
        self.assertIn("HEALTHCHECK", text)
        self.assertIn("/health", text)

    def test_compose_supports_puid_pgid(self):
        text = read("docker-compose.yml")
        self.assertIn("${PUID:-", text)
        self.assertIn("${PGID:-", text)

    def test_fork_deploys_its_published_image(self):
        text = read("docker-compose.yml")
        self.assertIn("ghcr.io/albert-li-sz/workbody-fhub:" + VERSION, text)
        self.assertNotIn("build:", text)
        self.assertIn('"0.0.0.0:8788:8788"', text)
        self.assertNotIn("ghcr.io/ardeyouxipianyi", text)
        ignored = read(".dockerignore")
        for pattern in ("accounts/", "usage/", ".env", "*.info"):
            self.assertIn(pattern, ignored)

    def test_original_project_declarations_and_license_are_preserved(self):
        text = read("README.md")
        self.assertTrue(text.startswith("# Workbody-FHUB"))
        self.assertIn("https://github.com/ardeyouxipianyi/workbuddy2api-hub", text)
        self.assertIn("100% Vibe Coding 协同产物", text)
        self.assertIn("本项目为非官方自托管网关，仅供技术研究", text)
        self.assertIn("本项目不提供任何账号及额度", text)
        self.assertIn("Credits & References", text)
        self.assertIn("MIT License", read("LICENSE.upstream"))
        self.assertIn("Apache License", read("LICENSE"))


class ReadmeTests(unittest.TestCase):
    def test_readme_suite_count_matches_the_tree(self):
        names = [n for n in os.listdir(os.path.join(ROOT, "tests"))
                 if n.startswith("_test_") and n.endswith((".py", ".js"))]
        py = len([n for n in names if n.endswith(".py")])
        js = len([n for n in names if n.endswith(".js")])
        expected = "%d 个套件：%d 个 Python + %d 个 JS" % (len(names), py, js)
        self.assertIn(expected, read("README.md"))


if __name__ == "__main__":
    unittest.main()
