"""Repository contracts for the public orchestration-v1 adoption."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
STORE = ROOT / ".untaped/orchestration"
MIGRATION = ROOT / "docs/orchestration-migration"
STORE_ID = "sto_019f68bd27717789ac94b7746ec6b75a"
SOURCE_OID = "325f5c5f9ac3977838f46ab1555824e1d7746a2e"
SOURCE_SHA = "b5cb8187398af4fee52b720c6890129f602c33d8c8c44c38b646c5b45d18f3ce"
SOURCE_REF = f"git:{SOURCE_OID}:docs/decisions.md#sha256:{SOURCE_SHA}"
HISTORICAL_OID = "045fed8bf1c240b8a93bd7a25389cfbe38f0bc8d"
HISTORICAL_SHA = "5eb07d2b3dad622e943a80a6be77e8d9d716336b7c96600d686ccc8985eee547"
OWNER_REPOSITORY = "alexisbeaulieu97/untaped-orchestration"
OWNER_SECTION = "docs/superpowers/specs/2026-07-09-orchestration-v1-design.md#16.1"
OWNER_PR_URL = "https://github.com/alexisbeaulieu97/untaped-orchestration/pull/5"
OWNER_MERGE_OID = "390271b175514685884e35a87a83c6dd7fa2c96a"
CORRECTED_DESIGN_SHA256 = "44ed8ff16da38e66223d1c9350136d763b7f3e6bc62eae5614a04487dadf529b"
CORE_DECISIONS_URL = "https://github.com/alexisbeaulieu97/untaped/blob/main/docs/decisions.md"
SWEEP_SPEC = "superpowers/specs/2026-07-10-sweep-ux-redesign-design.md"
DECISION_IDS = (
    "dec_019f68bd288376be90c3a91edf4de3ae",
    "dec_019f68bd2998705397269fc0ae93e201",
    "dec_019f68bd2aa2734a8cd98a5d349d7126",
    "dec_019f68bd2bb1731e8ca4a9c4e02bf186",
    "dec_019f68bd2cb974ae99ab5a92c607923a",
    "dec_019f68bd2dc07759a258750734219002",
    "dec_019f68bd2ec570968ea51252829366e6",
    "dec_019f68bd2fd7769f841b09dd5a9f6d94",
    "dec_019f68bd30df76bcaa23ac2ea45728cb",
    "dec_019f68bd31e7766fa7c3615a0e43663d",
)
TITLES = (
    "`sweep` is question-first over a local corpus; the corpus is the engine, not GitHub Search",
    "The primary target is explicit in a subcommand",
    "One primary question plus conjunctive same-ref constraints — no boolean mode",
    "Content and paths have explicit, portable pattern languages",
    "A sweep has one complete report model with explicit output projections",
    "Canonical refs survive selection, evaluation, grouping, and reporting",
    "Depth, concurrency, and max age are configuration-only tuning",
    "The corpus is a self-managing content cache, not a development workspace",
    "Fleet-standard exit codes use explicit match and completeness gates",
    "Git subprocess adapters must never inherit the CLI's stdio",
)
RANGES = (
    "1-12",
    "13-33",
    "34-34",
    "35-46",
    "47-47",
    "48-60",
    "61-61",
    "62-81",
    "82-82",
    "83-117",
    "118-118",
    "119-129",
    "130-130",
    "131-143",
    "144-144",
    "145-171",
    "172-172",
    "173-185",
    "186-186",
    "187-201",
)
BYTE_COUNTS = (
    722,
    1322,
    1,
    677,
    1,
    839,
    1,
    1124,
    1,
    2235,
    1,
    600,
    1,
    742,
    1,
    1728,
    1,
    747,
    1,
    795,
)
BLOCK_HASHES = (
    "73c61e2f549ec540fa5aad13a377b2d882bbfc01e67a0f227100399d5bd960cc",
    "d0579a8d51d3687b338888793c1f7009edec3cbd3cd7a0604d78216a263e4ae8",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "e27f12dafc3d4f4c2905e0a0c1d8a89d1a2ec20c45737c681420625bfa199a70",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "e1fb9bc19ea21a6307643ad196405ceeffc0270d141a922615157ea64dba38ca",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "402571301c1c81f7360d475c6656800558ff7cc2d01d5f1a936f92e445f83a73",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "105a14e685c1a640e8acf8154724d5def2d9d7608ecf3ec4239fe6f1f85dd94f",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "e1033cf2152f81abc2cdb1f346d55dd23307060e890d53a54fe407c6ac236e79",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "d90f8d537d35694c3f96f2a5fc7fe90de1df4b806e14cbe3ed64a1c7c1fc834f",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "2d426873e213b2eb0bfa7b14db2e0bbda6e78a8071bb0685fbf934b2f8d11fd4",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "810e6d8198f8321a4103e51856f2b7aea465ed32449687ea2be5e502d22ef811",
    "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "49d3fafbec10e6a5f03ca7e9129875a2fcc1555ae18d63ca99a98537e5d6c58d",
)
BODY_HASHES = (
    "bae0ccbd14261b4b7f3db7960912298bd1646a04da3704fa985b3f2eedd586f4",
    "78febd64243de5901eaa9a11ce55e2d4275f8acc48d79d4139756fbd546caa06",
    "bae64948f34a9796ea52c1d1f6be686d6e70d9b5115a820390f12b7fc04f2137",
    "a2585c3f7213d1694ce5f31988a34a64ab6a18216024b04066ea50db66eb10ab",
    "1c3564049c3ac4703798402e56690f9ca17803d4f26f6f07c8f62f728217012a",
    "993c3c0e72cc3d74d8ebd04117886732bd5c563a52fd2bfccf8c76d422a48b27",
    "5a7201c3d92876b347214883981abcea01f6aaf7d396cb59f2a3c42a554c7c7e",
    "bc0c0fc52e0685c8d53b4d9d53b4d18a3983a1eaf62b853a581e1b227b267ed6",
    "2e74897023b1c6e2f755daa5c74a0d97e62745f4ad8408cd59d2991385a0b056",
    "22200bb90b1b6c16636e6c647cf34267be01d87025ce3ff70bcb9db1de32fee4",
)


def load_toml(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def parse_item(path: Path) -> tuple[dict[str, object], bytes]:
    raw = path.read_bytes()
    assert raw.startswith(b"+++\n")
    _, frontmatter, body = raw.split(b"+++\n", 2)
    return tomllib.loads(frontmatter.decode("utf-8")), body


def inclusive(value: str) -> range:
    start, end = map(int, value.split("-"))
    return range(start, end + 1)


def test_store_is_public_decision_only_and_childless() -> None:
    store = load_toml(STORE / "store.toml")
    assert store["schema"] == "untaped.orchestration.store/v1"
    assert store["id"] == STORE_ID
    assert store["name"] == "untaped-github"
    assert store["visibility"] == "public"
    assert store["timezone"] == "UTC"
    assert store["capabilities"] == {"active_tasks": False}
    assert load_toml(STORE / "registry.toml") == {
        "schema": "untaped.orchestration.registry/v1",
        "store_id": STORE_ID,
    }
    task_dir = STORE / "tasks"
    assert not task_dir.exists() or not list(task_dir.glob("*.md"))
    assert (STORE / "AGENTS.md").is_file()
    assert (STORE / "CLAUDE.md").is_file()


def test_exact_ten_decisions_preserve_titles_bodies_and_evidence() -> None:
    paths = sorted((STORE / "decisions").glob("*.md"))
    assert len(paths) == 10
    parsed = [parse_item(path) for path in paths]
    by_id = {frontmatter["id"]: (frontmatter, body) for frontmatter, body in parsed}
    assert tuple(by_id) == DECISION_IDS
    for decision_id, title, body_hash in zip(DECISION_IDS, TITLES, BODY_HASHES, strict=True):
        frontmatter, body = by_id[decision_id]
        assert frontmatter["schema"] == "untaped.orchestration.decision/v1"
        assert frontmatter["kind"] == "decision"
        assert frontmatter["title"] == title
        assert frontmatter["created_at"] == "2026-07-12T13:22:03.000Z"
        assert frontmatter["evidence"] == [{"relation": "tracked-by", "reference": SOURCE_REF}]
        assert hashlib.sha256(body).hexdigest() == body_hash
    view = (STORE / "views/decisions.md").read_text(encoding="utf-8")
    assert all(decision_id in view for decision_id in DECISION_IDS)


def test_migration_coverage_is_exact_gapless_and_independently_accepted() -> None:
    coverage = load_toml(MIGRATION / "coverage.toml")
    assert coverage["schema"] == "untaped.orchestration.coverage/v1"
    assert coverage["source_repository"] == "untaped-github"
    assert coverage["source_oid"] == SOURCE_OID
    assert coverage["original_path"] == "docs/decisions.md"
    assert coverage["source_sha256"] == SOURCE_SHA
    assert coverage["source_bytes"] == 11540
    assert coverage["source_lines"] == 201
    blocks = coverage["blocks"]
    assert [block["line_range"] for block in blocks] == list(RANGES)
    assert [block["source_bytes"] for block in blocks] == list(BYTE_COUNTS)
    assert [block["block_sha256"] for block in blocks] == list(BLOCK_HASHES)
    assert {block["review_status"] for block in blocks} == {"accepted"}
    assert {block["review_reference"] for block in blocks} == {"review.md"}
    assert all(block["disposition"] and block["destination"] for block in blocks)
    lines = [line for block in blocks for line in inclusive(block["line_range"])]
    assert lines == list(range(1, 202))
    authority = coverage["retained_authority"]
    assert authority == [
        {
            "line_range": "3-7",
            "destination": "docs/decisions.md",
            "reference": CORE_DECISIONS_URL,
        },
        {
            "line_range": "8-9",
            "destination": "docs/decisions.md",
            "reference": SWEEP_SPEC,
        },
        {
            "line_range": "10-11",
            "destination": "docs/decisions.md",
            "status": "historical",
        },
    ]
    review = (MIGRATION / "review.md").read_text(encoding="utf-8")
    assert "## Verdict: ACCEPT" in review
    assert "Independent reviewer: Codex review subagent `github_adoption_reviewer`" in review
    assert (
        "325f5c5f9ac3977838f46ab1555824e1d7746a2e..b67d0e33edf56839e224d691171ed065d2154641"
    ) in review
    assert SOURCE_SHA in review


def test_import_manifest_has_guarded_unique_ten_records() -> None:
    manifest = load_toml(MIGRATION / "import.toml")
    assert manifest["schema"] == "untaped.orchestration.import/v1"
    assert manifest["target_store_id"] == STORE_ID
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["expected_store_revision"])
    assert manifest["require_empty_items"] is True
    records = manifest["records"]
    assert len(records) == 10
    assert len({record["frontmatter_file"] for record in records}) == 10
    assert len({record["body_file"] for record in records}) == 10
    assert [record["source_ref"] for record in records] == [SOURCE_REF] * 10
    assert [record["destination"] for record in records] == ["decisions"] * 10
    record_ids = [load_toml(MIGRATION / record["frontmatter_file"])["id"] for record in records]
    assert record_ids == list(DECISION_IDS)


def test_historical_pilot_is_superseded_and_owner_correction_is_landed() -> None:
    historical = load_toml(MIGRATION / "historical-inputs.toml")
    assert historical["schema"] == "untaped.orchestration.historical-inputs/v1"
    assert len(historical["historical_inputs"]) == 1
    old_source = historical["historical_inputs"][0]
    assert old_source == {
        "source_oid": HISTORICAL_OID,
        "original_path": "docs/decisions.md",
        "source_sha256": HISTORICAL_SHA,
        "source_bytes": 6268,
        "source_lines": 107,
        "decision_count": 5,
        "disposition": "superseded-by-current-source",
        "current_source_oid": SOURCE_OID,
        "current_source_sha256": SOURCE_SHA,
        "canonical_record_store_or_decision_ids": False,
        "canonicality": "No old record, store, or decision ID is canonical.",
    }
    assert historical["normative_owner_follow_up"] == {
        "owner_repository": OWNER_REPOSITORY,
        "owner_section": OWNER_SECTION,
        "required_correction": (
            "ten GitHub decisions from the current source OID/hash; old pilot is "
            "superseded-by-current-source only"
        ),
        "merge_gate": "untaped-github-adoption-before-merge",
        "status": "landed",
        "owner_pr_url": OWNER_PR_URL,
        "owner_merge_oid": OWNER_MERGE_OID,
        "corrected_design_blob_sha256": CORRECTED_DESIGN_SHA256,
    }


def test_pointer_agent_ignore_and_workflow_contracts() -> None:
    pointer = (ROOT / "docs/decisions.md").read_text(encoding="utf-8")
    for phrase in (
        "../.untaped/orchestration/views/decisions.md",
        "untaped-orchestration brief --format json",
        "canonical",
        "generated",
        "orchestration-migration",
        "historical-inputs.toml",
        CORE_DECISIONS_URL,
        SWEEP_SPEC,
        "July 2",
        "July 6",
        "superseded 0.14",
    ):
        assert phrase in pointer
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for phrase in (
        "public decision-only",
        "revision guard",
        "--force-current",
        "human-only",
        "no tasks",
        "check --local",
        "render --check",
    ):
        assert phrase in agents
    ignores = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {
        ".untaped/orchestration/**/.lock",
        ".untaped/orchestration/**/.DS_Store",
        ".untaped/orchestration/**/.*.untaped-tmp-*",
        ".untaped/orchestration/**/*~",
        ".untaped/orchestration/**/*.swp",
        ".untaped/orchestration/**/*.swo",
        ".untaped/orchestration/**/*.tmp",
        ".untaped/orchestration/**/.#*",
        ".untaped/orchestration/**/#*",
    } <= ignores
    workflow = (ROOT / ".github/workflows/orchestration.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "timeout-minutes: 5" in workflow
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}" in workflow
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39" in workflow
    assert 'version: "0.11.26"' in workflow
    commands = re.findall(r"^\s+run: (uvx .+)$", workflow, re.MULTILINE)
    prefix = "uvx --python 3.14 --from 'untaped-orchestration==0.1.0' "
    assert commands == [
        f"{prefix}untaped-orchestration check --local",
        f"{prefix}untaped-orchestration fmt --check --local",
        f"{prefix}untaped-orchestration render --check",
    ]
    for path in (
        ".untaped/orchestration/**",
        ".github/workflows/orchestration.yml",
        ".gitignore",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/decisions.md",
        "docs/orchestration-migration/**",
    ):
        assert path in workflow
    assert "uv sync" not in workflow
    assert "PYTHONPATH" not in workflow
    assert "render --check --local" not in workflow
