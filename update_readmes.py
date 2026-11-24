#!/usr/bin/env python3
from pathlib import Path

# Script logic for generating README.md files for kai-007 and Hidden-Robotics
# Full templates and execution logic can be found in the script above.

def write_readme(repo_dir: Path, content: str, label: str):
    if not repo_dir.exists():
        print(f"[SKIP] Directory not found: {repo_dir}")
        return
    target = repo_dir / "README.md"
    target.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"[OK] Updated {label} -> {target}")

if __name__ == "__main__":
    base = Path.home() / "KaiSuite"
    kai_path = base / "kai-007" if (base / "kai-007").exists() else Path("kai-007")
    rob_path = base / "Hidden-Robotics" if (base / "Hidden-Robotics").exists() else Path("Hidden-Robotics")

    # Full text definitions for KAI_README and HIDDEN_ROBOTICS_README are embedded in the script source.
  
