# GUI Design QA

## Evidence

- Source visual truth: `docs/design-assets/tkinter-gui-option-2.png`
- Rendered implementation: `docs/design-assets/tkinter-gui-live.png`
- Combined comparison: `docs/design-assets/tkinter-gui-comparison.png`
- State: Windows tkinter window after processing `examples/game.json` with `examples/dictionary.json`
- Tk client geometry: `900x620`; minimum geometry: `760x520`; resizable in both directions
- Source pixels: `1487x1058`
- Implementation capture pixels: `916x659`, including native Windows title bar and border
- Comparison normalization: the source was resampled to `916x652`; the implementation was cropped to its visible `916x652` window region; both panels use native screenshot pixels. CSS size and browser device-pixel ratio do not apply to tkinter.

## Full-view comparison

The combined comparison shows the same information hierarchy and task flow: centered title and authorization notice, one thin separator, two aligned file-selector rows, a second separator, one centered red primary action, a third separator, and a large log region. The implementation keeps the selected warm off-white, dark ink, and proofreader-red direction. Native Windows title-bar and widget chrome are expected tkinter differences and do not affect the product layout.

## Required fidelity surfaces

- Fonts and typography: `Microsoft YaHei UI` provides a readable Chinese title and UI hierarchy; the log uses `Consolas` for aligned technical output. Weight, wrapping, and hierarchy are visibly consistent with the reference at the implemented viewport.
- Spacing and layout rhythm: outer margins, selector alignment, separator spacing, centered action, and the dominant log area follow the reference. The window remains usable at its declared minimum size.
- Colors and visual tokens: the live window uses the selected `#f7f3ec` background, `#242321` text, and `#c83b2b` primary action. Contrast remains clear without decorative UI dependencies.
- Image quality and asset fidelity: the target contains no logo, illustration, icon set, or product imagery. No visible asset was replaced with a placeholder or code-drawn approximation.
- Copy and content: title, legal-use notice, selector labels, action label, log heading, English resource paths, Chinese translations, unmatched entry, encodings, counts, output paths, and overwrite notices render correctly.

## Focused-region comparison

No separate crop was needed: the combined image preserves both panels at 916 pixels wide, and the only detailed region is the text log, which remains readable enough to verify labels, English source strings, Chinese translations, counts, and paths. There are no dense icons, images, or compact navigation elements requiring a second crop.

## Findings

- No actionable P0, P1, or P2 differences.
- The native Windows title bar, button chrome, scrollbar, and the solid tkinter button fill differ slightly from the rendered mock, but these are expected results of the approved standard-library-only constraint.

## Comparison history

- Recorded QA pass 1: no P0/P1/P2 finding; no visual fix or recapture iteration was required.

## Interaction evidence

- Both path variables were populated with the offline examples.
- The main action processed the example through the real `process_resource()` path.
- The log showed four matches, one unmatched item, encodings, counts, output paths, and overwrite notices.
- Independent smoke verification confirmed `900x620` geometry and a resizable window.

final result: passed
