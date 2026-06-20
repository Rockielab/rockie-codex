from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "project-extension" / "agents" / "skills"

MIRRORED_COMMUNITY_SKILLS = {
    "build-agent",
    "diligence-deck",
    "excel",
    "physics",
    "powerpoint",
    "upstream-contribute",
}

FORBIDDEN_KEY_PATTERNS = (
    "email",
    "phone",
    "oauth",
    "token",
    "api_key",
    "apikey",
    "credential",
    "challenge",
    "nonce",
    "voter",
    "vote",
    "proposal_record",
    "raw_proposal",
    "review_comment",
    "moderation",
    "agent_run",
    "tenant_id",
    "user_id",
)


def load_frontmatter(skill_name):
    text = (SKILLS_ROOT / skill_name / "SKILL.md").read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{skill_name} is missing YAML frontmatter"
    parsed = yaml.safe_load(match.group(1))
    assert isinstance(parsed, dict), f"{skill_name} frontmatter must be a mapping"
    return parsed


def walk_keys(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = path + (str(key),)
            yield key_path
            yield from walk_keys(child, key_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_keys(child, path + (str(index),))


def assert_people(skill_name, frontmatter, field):
    people = frontmatter["attribution"].get(field)
    assert isinstance(people, list) and people, f"{skill_name} needs attribution.{field}"
    profiles = frontmatter["attribution"].get("profiles")
    assert isinstance(profiles, dict) and profiles, f"{skill_name} needs profiles"

    for person in people:
        assert isinstance(person.get("rockie_username"), str) and person["rockie_username"]
        assert isinstance(person.get("display_name"), str) and person["display_name"]
        refs = person.get("profile_refs")
        assert isinstance(refs, list) and refs, f"{skill_name} {field} needs profile_refs"
        for ref in refs:
            assert isinstance(ref, str) and ref
            assert ref in profiles, f"{skill_name} has dangling profile ref {ref}"
            profile = profiles[ref]
            assert isinstance(profile.get("provider"), str) and profile["provider"]
            assert isinstance(profile.get("url"), str) and profile["url"].startswith("https://")
            assert isinstance(profile.get("verified"), bool)


def test_expected_mirrored_community_skill_inventory():
    found = {
        path.parent.name
        for path in SKILLS_ROOT.glob("*/SKILL.md")
        if "\nscope: community\n" in path.read_text()
    }
    assert found == MIRRORED_COMMUNITY_SKILLS


def test_mirrored_community_skills_preserve_parseable_attribution():
    for skill_name in sorted(MIRRORED_COMMUNITY_SKILLS):
        frontmatter = load_frontmatter(skill_name)
        attribution = frontmatter.get("attribution")
        assert frontmatter.get("scope") == "community"
        assert isinstance(attribution, dict), f"{skill_name} attribution must be a mapping"
        assert attribution.get("schema_version") == 1
        assert_people(skill_name, frontmatter, "authors")
        assert_people(skill_name, frontmatter, "maintainers")

        source = attribution.get("source")
        assert isinstance(source, dict), f"{skill_name} needs attribution.source"
        assert source.get("repo") == "Rockielab/platform-skills"
        assert source.get("path") == f"skills/{skill_name}/SKILL.md"
        assert source.get("version") or source.get("sha")
        assert attribution.get("completeness") == "complete"


def test_mirrored_community_skill_frontmatter_omits_private_product_keys():
    for skill_name in sorted(MIRRORED_COMMUNITY_SKILLS):
        frontmatter = load_frontmatter(skill_name)
        for key_path in walk_keys(frontmatter):
            key = key_path[-1].lower().replace("-", "_")
            assert not any(pattern in key for pattern in FORBIDDEN_KEY_PATTERNS), (
                f"{skill_name} frontmatter contains forbidden key {'.'.join(key_path)}"
            )
