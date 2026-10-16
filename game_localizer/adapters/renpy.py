from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class RenPyAdapter(EngineAdapter):
    engine_id = "renpy"
    display_name = "Ren'Py"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_dir("game"):
            evidence.append(DetectionEvidence("renpy_game_dir", "game", "发现 game 目录", 20))
        scripts = tuple(
            path for path in snapshot.files_with_suffix(".rpy") if path.startswith("game/")
        )
        if scripts:
            evidence.append(
                DetectionEvidence("renpy_scripts", scripts[0], "发现 Ren'Py 源脚本", 65)
            )
        if snapshot.has_dir("renpy"):
            evidence.append(DetectionEvidence("renpy_runtime", "renpy", "发现 Ren'Py 运行库", 15))
        compiled = snapshot.files_with_suffix(".rpyc")
        if compiled:
            evidence.append(
                DetectionEvidence("renpy_compiled", compiled[0], "发现编译脚本", 10)
            )
        archives = snapshot.files_with_suffix(".rpa")
        if archives:
            evidence.append(DetectionEvidence("renpy_archive", archives[0], "发现 RPA 归档", 25))
        if not evidence:
            return None
        warnings = ()
        if not scripts and (compiled or archives):
            warnings = ("仅发现编译脚本或归档；阶段一不会提取或修改这些资源",)
        return self.build_result(evidence, warnings)
