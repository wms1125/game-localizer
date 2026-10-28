from game_localizer.models import DetectionReport, DetectionStatus


_STATUS_LABELS = {
    DetectionStatus.AUTO_SELECTED: "自动选择",
    DetectionStatus.STOPPED_UNCERTAIN: "置信度不足，已停止",
    DetectionStatus.STOPPED_CONFLICT: "候选冲突，已停止",
    DetectionStatus.UNKNOWN: "无法确定",
}


def format_detection_report(report: DetectionReport) -> str:
    lines = [f"项目目录: {report.root}", f"检测状态: {_STATUS_LABELS[report.status]}"]
    for candidate in report.candidates:
        lines.append(
            f"候选引擎: {candidate.display_name} ({candidate.engine_id}) "
            f"置信度 {candidate.score}% / {candidate.capability.value} / {candidate.maturity.value}"
        )
        for evidence in candidate.evidence:
            lines.append(f"  - [{evidence.weight:+d}] {evidence.description}: {evidence.path}")
        for warning in candidate.warnings:
            lines.append(f"  - 警告: {warning}")
    if report.selected_engine:
        lines.append(f"选定引擎: {report.selected_engine}")
    else:
        lines.append("未选定引擎；项目未修改。")
    return "\n".join(lines)
