from pathlib import Path

from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class GodotAdapter(EngineAdapter):
    engine_id = "godot"
    display_name = "Godot"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_file("project.godot"):
            evidence.append(
                DetectionEvidence("godot_project", "project.godot", "发现 Godot 项目文件", 85)
            )
        if snapshot.has_dir(".godot"):
            evidence.append(DetectionEvidence("godot_cache", ".godot", "发现 Godot 项目缓存", 10))
        resources = snapshot.files_with_suffix(".gd") + snapshot.files_with_suffix(".tscn")
        if resources:
            evidence.append(
                DetectionEvidence("godot_resources", resources[0], "发现 Godot 项目资源", 5)
            )

        packs = snapshot.root_files_with_suffix(".pck")
        if packs:
            pack_stems = {Path(path).stem for path in packs}
            executables = snapshot.root_files_with_suffix(".exe")
            matching = next((path for path in executables if Path(path).stem in pack_stems), None)
            pack = next(
                (path for path in packs if matching and Path(path).stem == Path(matching).stem),
                packs[0],
            )
            evidence.append(DetectionEvidence("godot_pack", pack, "发现 Godot PCK", 60))
            if matching:
                evidence.append(
                    DetectionEvidence("godot_executable", matching, "发现同名可执行文件", 25)
                )

        if not evidence:
            return None
        warnings = (
            ("PCK 只用于检测，不会被提取或修改",)
            if packs
            else ("此阶段仅提供只读检测",)
        )
        return self.build_result(evidence, warnings)
