from game_localizer.adapters.base import EngineAdapter
from game_localizer.models import DetectionEvidence, DetectionResult, MaturityLevel
from game_localizer.scanner import ProjectSnapshot


class UnityAdapter(EngineAdapter):
    engine_id = "unity"
    display_name = "Unity"
    maturity = MaturityLevel.EXPERIMENTAL

    def detect(self, snapshot: ProjectSnapshot) -> DetectionResult | None:
        evidence: list[DetectionEvidence] = []
        if snapshot.has_dir("assets"):
            evidence.append(DetectionEvidence("unity_assets", "Assets", "发现 Unity Assets 目录", 25))
        if snapshot.has_file("projectsettings/projectversion.txt"):
            evidence.append(
                DetectionEvidence(
                    "unity_version", "ProjectSettings/ProjectVersion.txt", "发现 Unity 项目版本", 45
                )
            )
        if snapshot.has_file("packages/manifest.json"):
            evidence.append(
                DetectionEvidence("unity_packages", "Packages/manifest.json", "发现 Unity 包清单", 35)
            )
        if snapshot.has_file("unityplayer.dll"):
            evidence.append(
                DetectionEvidence("unity_player", "UnityPlayer.dll", "发现 Unity Player", 45)
            )
        data_dirs = snapshot.root_dirs_with_suffix("_data")
        if data_dirs:
            manager_dir = next(
                (
                    data_dir
                    for data_dir in data_dirs
                    if any(
                        path.startswith(f"{data_dir}/")
                        for path in snapshot.files_named("globalgamemanagers")
                    )
                ),
                data_dirs[0],
            )
            evidence.append(
                DetectionEvidence("unity_data", manager_dir, "发现 Unity Data 目录", 30)
            )
            managers = tuple(
                path
                for path in snapshot.files_named("globalgamemanagers")
                if path.startswith(f"{manager_dir}/")
            )
            if managers:
                evidence.append(
                    DetectionEvidence("unity_managers", managers[0], "发现 Unity 全局资源", 35)
                )
        if not evidence:
            return None
        packaged = snapshot.has_file("unityplayer.dll") or bool(data_dirs)
        warnings = (
            ("Unity 成品二进制资源只用于检测，不会被提取或修改",)
            if packaged
            else ("此阶段仅提供只读检测",)
        )
        return self.build_result(evidence, warnings)
