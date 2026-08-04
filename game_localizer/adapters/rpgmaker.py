from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class _RpgMakerAdapter(EngineAdapter):
    project_file: str
    core_candidates: tuple[str, ...]

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_file(self.project_file):
            evidence.append(
                DetectionEvidence(
                    "rpgmaker_project",
                    self.project_file,
                    f"发现 {self.display_name} 项目标记",
                    60,
                )
            )
        core = next((path for path in self.core_candidates if snapshot.has_file(path)), None)
        if core:
            evidence.append(DetectionEvidence("rpgmaker_core", core, "发现引擎核心脚本", 45))
        system = next(
            (path for path in ("data/system.json", "www/data/system.json") if snapshot.has_file(path)),
            None,
        )
        if system:
            evidence.append(DetectionEvidence("rpgmaker_system", system, "发现系统数据库", 35))
        if snapshot.has_file("package.json") or snapshot.has_file("www/package.json"):
            evidence.append(DetectionEvidence("rpgmaker_package", "package.json", "发现 NW.js 配置", 10))
        if not evidence:
            return None
        return self.build_result(evidence, ("阶段一仅提供只读检测",))


class RpgMakerMZAdapter(_RpgMakerAdapter):
    engine_id = "rpg_maker_mz"
    display_name = "RPG Maker MZ"
    maturity = MaturityLevel.EXPERIMENTAL
    project_file = "game.rmmzproject"
    core_candidates = ("js/rmmz_core.js", "www/js/rmmz_core.js")


class RpgMakerMVAdapter(_RpgMakerAdapter):
    engine_id = "rpg_maker_mv"
    display_name = "RPG Maker MV"
    maturity = MaturityLevel.EXPERIMENTAL
    project_file = "game.rpgproject"
    core_candidates = ("js/rpg_core.js", "www/js/rpg_core.js")
