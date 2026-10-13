from pathlib import Path


def render(path, online=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, Rectangle

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    fig.patch.set_facecolor('white')
    ax.set(xlim=(0, 16), ylim=(0, 9))
    ax.axis('off')
    green, blue, ink, red = '#167d73', '#426fcc', '#213a40', '#b65463'
    ax.text(.35, 8.63, 'EvoJev: Single-Pass Executable Experience' if online else 'EvoJev: Frozen Decisions, Executable Experience', fontsize=22, weight='bold', color=ink)
    ax.text(.35, 8.21, 'Source-grounded RCA | JEV-guided acquisition | Post-case Harness evolution', color='#627880', fontsize=12)

    def band(y, height, color, title):
        ax.add_patch(Rectangle((.2, y), 15.6, height, facecolor=color, edgecolor='none'))
        ax.text(.4, y + height - .32, title, fontsize=12, weight='bold', color=ink)

    def box(x, y, color, title, lines):
        ax.add_patch(Rectangle((x, y), 3.52, 1.7, facecolor='white', edgecolor=color, linewidth=1.05))
        heading = ax.text(x + .17, y + 1.4, title, fontsize=11.2, weight='bold', color=color)
        ax.plot([x + .17, x + 3.35], [y + 1.17] * 2, color=color, linewidth=1.5)
        body = ax.text(x + .17, y + 1.01, '\n'.join(lines), va='top', fontsize=9.5, linespacing=1.65, color=ink)
        fig.canvas.draw()
        available = ax.transData.transform((x + 3.35, y))[0] - ax.transData.transform((x + .17, y))[0]
        for text in (heading, body):
            width = text.get_window_extent(fig.canvas.get_renderer()).width
            if width > available:
                text.set_fontsize(text.get_fontsize() * available / width * .98)

    def arrow(a, b, color):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle='-|>', mutation_scale=12, linewidth=1.3, color=color))

    positions = [.35, 4.25, 8.15, 12.05]
    band(4.7, 2.95, '#edf7f3', 'I. DIAGNOSIS: PUBLIC OBSERVATIONS ONLY')
    box(positions[0], 5.12, green, 'Acquire and bind evidence', ['Logs, events, workload state', 'Unhealthy Pod descriptions first', 'Source discovery + read both charged'])
    box(positions[1], 5.12, green, 'JEV + historical experience', ['Frozen classification / action priors', 'Anonymized source-bound features', 'Probability is not causal proof'])
    box(positions[2], 5.12, green, 'Bounded evidence planning', ['PUCT: 96 simulations, 3-call horizon', 'Contrastive or coverage objective', '72 actual calls; replan after checks'])
    box(positions[3], 5.12, green, 'Lock first answer: case t' if online else 'Persist object AND cause', ['Object AND cause; immutable first trace', 'No retry or corrected score replacement', 'Feedback unavailable before commit'] if online else ['Verified Harness candidate constraints', 'Actual tool trace + provenance hash', 'No final-case labels to the solver'])
    for x in positions[:-1]:
        arrow((x + 3.52, 5.97), (x + 3.9, 5.97), green)

    band(1.72, 2.65, '#eef2fc', 'II. AFTER EVERY CASE: PAST FEEDBACK ONLY' if online else 'II. POST-CASE EVOLUTION: COMPLETED HISTORICAL CASES ONLY')
    box(positions[0], 1.94, blue, 'Release completed feedback' if online else 'Historical residuals', ['Case t feedback released after first answer', 'Past observations retained; no new tools', 'Never open future-case labels'] if online else ['144 preserved incident traces', 'Current errors, balanced cause coverage', 'Exclude final evaluation feedback'])
    box(positions[1], 1.94, blue, 'Qwen3.5-27B advisor', ['One reusable, atomic evidence rule', 'Cited observations + counterexamples', 'No case-ID or answer lookup'])
    box(positions[2], 1.94, blue, 'Cached predicate admission' if online else 'Cross-incident admission', ['Source / ownership / semantic checks', 'At least 2 past cases; precision >= 95%', 'No conflicting proof on past correct cases'] if online else ['Evidence / ownership / semantic tests', 'Support beyond the proposing case', 'Historical repairs + zero regressions'])
    box(positions[3], 1.94, blue, 'Harness H_(t+1)' if online else 'Versioned Harness', ['Accept / reject / no update', 'Applies only to subsequent cases', 'Refresh past-only experience every 8 cases'] if online else ['Separate 36-case actual acquisition gate', 'Accept / reject; preserve prior versions', 'JEV weights remain frozen'])
    for x in positions[:-1]:
        arrow((x + 3.52, 2.79), (x + 3.9, 2.79), blue)
    ax.plot([13.82, 13.82, .24, .24], [5.12, 4.52, 4.52, 3.05], color=blue, linewidth=1.2)
    arrow((.24, 3.05), (.35, 3.05), blue)
    ax.text(6.05, 4.57, 'After immutable first prediction only' if online else 'Completed historical feedback only', fontsize=10, color=blue)
    ax.plot([13.82, 13.82, .05, .05, 4.13], [1.94, 1.51, 1.51, 6.97, 6.97], color=red, linestyle='--', linewidth=1)
    arrow((4.13, 6.97), (4.42, 6.82), red)
    ax.text(5.65, 1.36, 'Next case only; never re-answer case t; JEV weights remain frozen' if online else 'Reusable executable experience, not neural-weight distillation', color=red, fontsize=10)
    ax.plot([.35, 15.57], [1.08, 1.08], color='#dce5e8', linewidth=1)
    ax.text(.35, .8, 'III. PREQUENTIAL FIRST-ANSWER EVALUATION' if online else 'III. FROZEN COMPARISON', fontsize=11, color=ink, weight='bold')
    ax.text(.35, .5, '754 unique cases  >  One actual diagnosis each  >  Never revise old scores  >  Audit the complete version chain' if online else 'Stop advisor  >  Freeze six methods  >  Complete 6 x 754 actual predictions  >  Open labels for scoring', fontsize=11, color=ink)
    ax.text(.35, .16, 'Public benchmark previously used. Predicate validation is not re-inference or a guarantee of future accuracy; no held-out novelty claim.' if online else 'Full754 includes development cases; report frozen155 separately. Best observed method is a post-hoc comparison, not a casewise oracle.', fontsize=9.2, color='#627880')
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160, facecolor='white', bbox_inches='tight', pad_inches=.1)
    plt.close(fig)
