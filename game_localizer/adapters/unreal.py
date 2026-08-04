from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class UnrealAdapter(EngineAdapter):
    engine_id = "unreal"
    display_name = "Unreal Engine"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        projects = snapshot.root_files_with_suffix(".uproject")
        if projects:
            evidence.append(
                DetectionEvidence("unreal_project", projects[0], "发现 Unreal 项目文件", 80)
            )
        if projects and snapshot.has_dir("config"):
            evidence.append(DetectionEvidence("unreal_config", "Config", "发现 Unreal 配置目录", 10))
        if projects and snapshot.has_dir("content"):
            evidence.append(DetectionEvidence("unreal_content", "Content", "发现 Unreal Content 目录", 10))
        for suffix, code, weight in (
            (".pak", "unreal_pak", 45),
            (".ucas", "unreal_ucas", 30),
            (".utoc", "unreal_utoc", 30),
        ):
            matches = snapshot.files_with_suffix(suffix)
            if matches:
                evidence.append(
                    DetectionEvidence(code, matches[0], f"发现 Unreal {suffix} 容器", weight)
                )
        if not evidence:
            return None
        packaged = any(
            item.code in {"unreal_pak", "unreal_ucas", "unreal_utoc"} for item in evidence
        )
        warnings = (
            ("Unreal 封包只用于检测，不会被提取或修改",)
            if packaged
            else ("此阶段仅提供只读检测",)
        )
        return self.build_result(evidence, warnings)
