"""GUI for pattern_generator.py: pick total time and stage counts, see the random \
pattern.

    cd "04_synthetic_data" && streamlit run pattern_app.py

(run from this folder so .streamlit/config.toml - the app theme - is picked up)

Same generator as the command line (pattern_generator.generate), so the stage
map arrows come from flow_check.ALLOWED (Shut-down split into Cooling and At
ambient, pattern_generator.ARROWS) and the default stage lengths from
library/episodes.csv. Each block also gets a gas / air supply plan from the
flow controllers (pattern_generator.plan_phases / phase_table: Air only,
Forming gas, Forming gas without air, N2 purge, Natural gas, Plant off, with real \
flows in ln/min).
"Fill with real data" runs pattern_filler.fill on the pattern shown (all
sensors incl. the present FIRC 1,1,3 tag, 1-min rows, copied from real
episodes that match each block's supply plan).
"""

import datetime as dt
import random
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pattern_filler as pf  # noqa: E402
import pattern_generator as pg  # noqa: E402

# muted engineering palette: cold side blues, heat-up amber, hot side red / violet, load
# green
COLOR = {
    "Idle": "#8A94A6",
    pg.SD_COOL: "#3B6FB6",
    pg.SD_AMB: "#86B4DD",
    "Start-up": "#E08A2E",
    "Hot standby": "#C4473D",
    "Thermal adjustment": "#8B6BB5",
    "Part load": "#2E9A6B",
    "Rated power": "#D4AE34",
}
PH_COLOR = {
    "Plant off": "#C3C9D2",
    "Air only": "#8CC4E8",
    "Forming gas (N2 + H2)": "#A98BCB",
    pg.PH_FORMING_DRY: "#D45D9A",
    "N2 purge": "#4F6D9A",
    "Natural gas": "#E3A13B",
}
DEFAULT_COUNT = {
    pg.SD_COOL: 3,
    pg.SD_AMB: 1,
    "Start-up": 3,
    "Hot standby": 5,
    "Thermal adjustment": 2,
    "Part load": 3,
}
INK, MUTED, GRID = "#1C2430", "#5B6573", "#E4E8EE"
CHART_FONT = 15  # px, axis / legend labels of every chart (large for readability)
FONT = "Inter, Segoe UI, Helvetica, Arial, sans-serif"

st.set_page_config(
    page_title="SOFC Pattern Generator", page_icon=":material/timeline:", layout="wide"
)

st.markdown(
    f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stDataFrame, button, input, textarea {{ \
font-family: {FONT}; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 2400px; }}
h1, h2, h3, h4 {{ letter-spacing: -0.01em; color: {INK}; }}
.hero {{ background: linear-gradient(120deg, #13314F 0%, #1F4E79 55%, #2D6A9F 100%);
         border-radius: 14px; padding: 22px 28px; color: #fff; margin-bottom: 18px;
         box-shadow: 0 4px 18px rgba(19, 49, 79, .18); }}
.hero h1 {{ color: #fff; font-size: 1.65rem; font-weight: 700; margin: 0 0 4px 0; \
padding: 0; }}
.hero p {{ color: #D6E3F0; margin: 0; font-size: .95rem; }}
.chips {{ margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; }}
.chip {{ background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.22);
         border-radius: 999px; padding: 3px 12px; font-size: .78rem; color: #EAF1F8; }}
.section {{ font-size: .78rem; font-weight: 600; letter-spacing: .08em; \
text-transform: uppercase;
            color: {MUTED}; margin: 22px 0 8px 2px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 18px; font-size: 1rem; color: {MUTED}; \
margin: 2px 0 6px 2px; }}
.legend span i {{ display: inline-block; width: 15px; height: 15px; border-radius: 3px;
                  margin-right: 6px; vertical-align: -1px; }}
.note {{ font-size: .92rem; color: {MUTED}; margin-top: -4px; }}
div[data-testid="stMetric"] {{ background: #fff; }}
div[data-testid="stMetricLabel"] p {{ font-size: .78rem; color: {MUTED}; \
text-transform: uppercase;
                                      letter-spacing: .05em; font-weight: 600; }}
div[data-testid="stMetricValue"] {{ font-size: 1.55rem; font-weight: 600; color: \
{INK}; }}
div[data-testid="stVerticalBlockBorderWrapper"] > div > \
div[data-testid="stVerticalBlock"] {{ gap: .6rem; }}
div[data-testid="stExpander"] details {{ background: #fff; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {GRID}; }}
.stTabs [data-baseweb="tab"] {{ padding: 8px 16px; font-weight: 500; }}
section[data-testid="stSidebar"] {{ border-right: 1px solid {GRID}; }}
section[data-testid="stSidebar"] h3 {{ font-size: .78rem; text-transform: uppercase; \
letter-spacing: .08em;
                                       color: {MUTED}; margin-top: .6rem; }}
</style>""",
    unsafe_allow_html=True,
)


@alt.theme.register("sofc", enable=True)
def sofc_theme():
    axis = dict(
        labelFont=FONT,
        titleFont=FONT,
        labelColor=MUTED,
        titleColor=MUTED,
        labelFontSize=CHART_FONT,
        titleFontSize=CHART_FONT,
        titleFontWeight=500,
        gridColor=GRID,
        domain=False,
        tickColor=GRID,
    )
    return alt.theme.ThemeConfig(
        config=dict(
            background="transparent",
            font=FONT,
            view=dict(stroke=None),
            axis=axis,
            axisY=dict(labelPadding=8),
            axisX=dict(grid=False, domain=True, domainColor=GRID),
            legend=dict(
                labelFont=FONT,
                titleFont=FONT,
                labelColor=MUTED,
                titleColor=MUTED,
                labelFontSize=CHART_FONT,
                symbolType="square",
                symbolSize=180,
            ),
            header=dict(
                labelFont=FONT,
                labelColor=INK,
                labelFontSize=CHART_FONT,
                labelFontWeight=500,
            ),
            title=dict(
                font=FONT,
                color=INK,
                fontWeight=600,
                anchor="start",
                fontSize=CHART_FONT + 2,
            ),
        )
    )


def chart(c, **kw):
    st.altair_chart(c, theme=None, width="stretch", **kw)


def section(text):
    st.markdown(f'<div class="section">{text}</div>', unsafe_allow_html=True)


def legend(items):
    st.markdown(
        '<div class="legend">'
        + "".join(f'<span><i style="background:{c}"></i>{s}</span>' for s, c in items)
        + "</div>",
        unsafe_allow_html=True,
    )


DT_COLS = {
    "start": st.column_config.DatetimeColumn("Start", format="YYYY-MM-DD HH:mm"),
    "end": st.column_config.DatetimeColumn("End", format="YYYY-MM-DD HH:mm"),
}


@st.cache_resource
def real_library():
    return pf.Library()


@st.cache_data
def library():
    return pg.library_bounds(), pg.library_counts()


@st.cache_data
def flow_levels():
    return pg.flow_levels()


PH_SCALE = alt.Scale(domain=list(pg.PHASES), range=[PH_COLOR[p] for p in pg.PHASES])

bounds0, n_real = library()
if "seed" not in st.session_state:
    st.session_state.seed = random.randrange(10**6)

# ---------------------------------------------------------------- header
st.markdown(
    f"""<div class="hero">
<h1>SOFC Stage Pattern Generator</h1>
<p>Synthetic operating timelines that follow the plant's stage map, with real stage \
lengths,
gas / air supply plans and optional fill with recorded sensor data.</p>
<div class="chips"><span class="chip">Stage map · flow_check.ALLOWED · \
{len(pg.ARROWS)} arrows</span>
<span class="chip">Library · {sum(n_real.values())} real stage blocks</span>
<span class="chip">Supply plan · {len(pg.FLOWS)} flow controllers</span>
<span class="chip">1-min resolution</span></div></div>""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- inputs
with st.sidebar:
    st.markdown("### Time frame")
    hours = st.number_input("Total time (hours)", min_value=1.0, value=200.0, step=10.0)
    c1, c2 = st.columns(2)
    day = c1.date_input("Start date", dt.date(2026, 1, 1))
    clock = c2.time_input("Start time", dt.time(0, 0))
    st.markdown("### Sequence")
    first = st.selectbox(
        "Start stage",
        ["(any)"] + pg.STAGES,
        index=1 + pg.STAGES.index(pg.SD_COOL),
        help="Stage of the first block",
    )
    ends = [
        s for s in pg.STAGES if any(b == s for _, b in pg.ARROWS)
    ]  # Idle has no arrow into it
    last = st.selectbox(
        "End stage",
        ["(any)"] + ends,
        help="Stage of the last block; extra blocks are added if the counts "
        "cannot reach it along the stage map (Shut-down only after Hot standby)",
    )
    st.markdown("### Randomness")
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    c1.number_input(
        "Random seed",
        min_value=0,
        step=1,
        key="seed",
        help="Same seed + same settings = same pattern",
    )
    c2.button(
        "New",
        icon=":material/casino:",
        width="stretch",
        on_click=lambda: st.session_state.update(seed=random.randrange(10**6)),
    )
    n_pat = st.number_input(
        "Number of patterns",
        min_value=1,
        max_value=100,
        value=1,
        help="Pattern k uses seed + k - 1",
    )
    st.divider()
    st.caption(
        "Stage lengths default to the real min–max per stage; all blocks add up to the "
        "total time."
    )

table = pd.DataFrame(
    {
        "Stage": pg.STAGES,
        "Count": [DEFAULT_COUNT.get(s, 0) for s in pg.STAGES],
        "Min length (h)": [
            round(bounds0[s][0], 2) if s in bounds0 else None for s in pg.STAGES
        ],
        "Max length (h)": [
            round(bounds0[s][1], 2) if s in bounds0 else None for s in pg.STAGES
        ],
        "Real episodes": [n_real.get(s, 0) for s in pg.STAGES],
    }
)

section("Configuration")
left, right = st.columns([3, 2], gap="medium")
with left, st.container(border=True):
    st.markdown("**Stages**")
    edited = st.data_editor(
        table,
        hide_index=True,
        width="stretch",
        key="stages",
        disabled=["Stage", "Real episodes"],
        column_config={
            "Count": st.column_config.NumberColumn(min_value=0, max_value=200, step=1),
            "Min length (h)": st.column_config.NumberColumn(
                min_value=0.0, format="%.2f"
            ),
            "Max length (h)": st.column_config.NumberColumn(
                min_value=0.0, format="%.2f"
            ),
            "Real episodes": st.column_config.NumberColumn(
                help="Stage blocks in the real data the default lengths come from"
            ),
        },
    )

counts = dict(zip(edited["Stage"], edited["Count"].fillna(0).astype(int)))
bounds, problems = {}, []
for _, r in edited.iterrows():
    lo, hi = r["Min length (h)"], r["Max length (h)"]
    if pd.notna(lo) and pd.notna(hi):
        if lo > hi:
            problems.append(f"{r['Stage']}: min length is above max length")
        bounds[r["Stage"]] = (float(lo), float(hi))
    elif counts[r["Stage"]] > 0:
        problems.append(f"{r['Stage']}: no real data, fill in its min and max length")

used = {s: n for s, n in counts.items() if n > 0}
need_lo = sum(n * bounds[s][0] for s, n in used.items() if s in bounds)
need_hi = sum(n * bounds[s][1] for s, n in used.items() if s in bounds)
with left:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stage blocks", sum(used.values()), border=True)
    m2.metric("Target total", f"{hours:g} h", border=True)
    m3.metric("Shortest possible", f"{need_lo:.1f} h", border=True)
    m4.metric("Longest possible", f"{need_hi:.1f} h", border=True)

# ---------------------------------------------------------------- generate
t0 = pd.Timestamp(dt.datetime.combine(day, clock))
pats, errors = [], []
if not problems:
    for k in range(int(n_pat)):
        try:
            df = pg.generate(
                hours,
                counts,
                bounds,
                None if first == "(any)" else first,
                None if last == "(any)" else last,
                st.session_state.seed + k,
                t0,
            )
            added = df.attrs["added"]
            df = df.assign(pattern=k + 1, seed=st.session_state.seed + k)
            df.attrs["added"] = added
            pats.append(df)
        except ValueError as err:
            errors.append(str(err))
            break


def stage_map(df=None):
    """Stage map as DOT; arrows used in `df` are bold with how often they are used."""
    use = (
        {}
        if df is None
        else (
            pd.Series(list(zip(df["step"][:-1], df["step"][1:])))
            .value_counts()
            .to_dict()
        )
    )
    shown = [s for s in pg.STAGES if s in bounds or counts[s] > 0]
    lines = [
        'digraph { rankdir=TB; bgcolor="transparent"; nodesep=0.5; ranksep=0.45; '
        'node [shape=box style="rounded,filled" penwidth=0 margin="0.22,0.1" '
        'fontname="Segoe UI Semibold" fontsize=15 fontcolor=white]; '
        f'edge [fontname="Segoe UI" fontsize=13 fontcolor="{INK}" arrowsize=0.7];'
    ]
    for s in shown:  # stages with count 0 are greyed out
        fill, font = (COLOR[s], "white") if counts[s] else ("#E4E8EE", "#8A94A6")
        lines.append(f'"{s}" [fillcolor="{fill}" fontcolor="{font}"];')
    for a, b in sorted(pg.ARROWS):
        if a in shown and b in shown:
            n = use.get((a, b), 0)
            lines.append(
                f'"{a}" -> "{b}" [color="{INK if n else "#C9CFD8"}" '
                f"penwidth={1.2 + min(n, 6) * 0.5 if n else 0.8}"
                f"{f' label=<<b>{n}</b>>' if n else ''}];"
            )
    return "\n".join(lines + ["}"])


with right, st.container(border=True):
    st.markdown("**Stage map**")
    st.graphviz_chart(stage_map(pats[0] if pats else None), width="stretch")
    st.markdown(
        '<div class="note">Grey = allowed transition · dark with a number = used in '
        "the pattern shown.</div>",
        unsafe_allow_html=True,
    )

for msg in problems + errors:
    st.error(msg, icon=":material/error:")
if not pats:
    st.stop()

# ---------------------------------------------------------------- pattern overview
section("Generated pattern")
pick = 1
if len(pats) > 1:
    pick = st.select_slider(
        "Pattern to show", options=list(range(1, len(pats) + 1)), value=1
    )
df = pats[pick - 1]
if df.attrs.get("added"):
    st.info(
        "These counts cannot follow the stage map as given, so the fewest extra blocks "
        "needed were added: "
        + ", ".join(f"{n} × {s}" for s, n in df.attrs["added"].items()),
        icon=":material/info:",
    )

ph = pg.phase_table(df)
flow_cols = [c for c in pg.FLOWS if c in ph.columns]
arrows_used = len(set(zip(df["step"][:-1], df["step"][1:])))
m = st.columns(5)
m[0].metric("Pattern", f"{pick} of {len(pats)}", border=True)
m[1].metric("Seed", int(df["seed"].iat[0]), border=True)
m[2].metric("Blocks", len(df), border=True)
m[3].metric("Transitions used", f"{arrows_used} / {len(pg.ARROWS)}", border=True)
m[4].metric("Supply phases", len(ph), border=True)

order = [s for s in pg.STAGES if s in set(df["step"])]
scale = alt.Scale(domain=order, range=[COLOR[s] for s in order])
summary = (
    df.groupby("step")["duration_h"]
    .agg(blocks="count", total_h="sum", mean_h="mean", min_h="min", max_h="max")
    .reindex(order)
    .reset_index()
)
summary["share"] = summary["total_h"] / summary["total_h"].sum()

t_time, t_supply, t_summary, t_fill = st.tabs(
    [
        ":material/view_timeline: Timeline",
        ":material/air: Gas & air supply",
        ":material/table_chart: Summary & blocks",
        ":material/database: Fill with real data",
    ]
)

with t_time, st.container(border=True):
    legend([(s, COLOR[s]) for s in order])
    lane = "Gas / air supply"
    rows = order + [lane]
    tip = [
        alt.Tooltip("seq:Q", title="Block"),
        alt.Tooltip("step:N", title="Stage"),
        alt.Tooltip("start:T", title="Start", format="%Y-%m-%d %H:%M"),
        alt.Tooltip("end:T", title="End", format="%Y-%m-%d %H:%M"),
        alt.Tooltip("duration_h:Q", title="Length (h)", format=".2f"),
    ]
    path = (
        alt.Chart(df)
        .mark_line(
            interpolate="step-after",
            color="#AEB6C2",
            strokeWidth=1.5,
            strokeDash=[4, 4],
        )
        .encode(x=alt.X("start:T", title=None), y=alt.Y("step:N", sort=rows))
    )
    bars = (
        alt.Chart(df)
        .mark_bar(cornerRadius=5, height=40)
        .encode(
            x=alt.X(
                "start:T",
                title=None,
                axis=alt.Axis(
                    format="%d %b %H:%M", labelAngle=0, grid=True, gridColor=GRID
                ),
            ),
            x2="end:T",
            y=alt.Y("step:N", sort=rows, title=None),
            color=alt.Color("step:N", scale=scale, legend=None),
            tooltip=tip,
        )
    )
    supply = (
        alt.Chart(ph.assign(step=lane))
        .mark_bar(cornerRadius=4, height=40)
        .encode(
            x="start:T",
            x2="end:T",
            y=alt.Y("step:N", sort=rows),
            color=alt.Color("phase:N", scale=PH_SCALE, legend=None),
            tooltip=[
                alt.Tooltip("seq:Q", title="Block"),
                alt.Tooltip("step:N", title="Stage"),
                alt.Tooltip("phase:N", title="Supply"),
                alt.Tooltip("duration_h:Q", title="Length (h)", format=".2f"),
                alt.Tooltip("source_episode:N", title="Copied from"),
            ]
            + [alt.Tooltip(f"{c}:Q", format=".0f") for c in flow_cols],
        )
    )
    chart(
        alt.layer(path, bars, supply)
        .resolve_scale(color="independent")
        .properties(height=72 * len(rows) + 50)
        .interactive(bind_y=False)
    )
    legend([(p, PH_COLOR[p]) for p in pg.PHASES if p in set(ph["phase"])])
    st.markdown(
        '<div class="note">Drag to pan, scroll to zoom in time; the bottom row is the '
        "planned gas / air supply. "
        "Hover a block for times and flows.</div>",
        unsafe_allow_html=True,
    )

with t_supply:
    with st.container(border=True):
        st.markdown("**Planned flows per controller** (ln/min)")
        if flow_cols:
            legend([(p, PH_COLOR[p]) for p in pg.PHASES if p in set(ph["phase"])])
            for i, c in enumerate(
                flow_cols
            ):  # one full-width strip per controller (facets do not stretch)
                chart(
                    alt.Chart(ph.rename(columns={c: "ln/min"}))
                    .mark_rule(strokeWidth=6, strokeCap="round")
                    .encode(
                        x=alt.X(
                            "start:T",
                            title=None,
                            axis=alt.Axis(labelAngle=0, labels=i == len(flow_cols) - 1),
                        ),
                        x2="end:T",
                        y=alt.Y("ln/min:Q", title=None, axis=alt.Axis(tickCount=5)),
                        color=alt.Color("phase:N", scale=PH_SCALE, legend=None),
                        tooltip=[
                            alt.Tooltip("seq:Q", title="Block"),
                            alt.Tooltip("phase:N", title="Supply"),
                            alt.Tooltip("ln/min:Q", title=c, format=".0f"),
                        ],
                    )
                    .properties(
                        height=180,
                        title=alt.Title(
                            c, fontSize=CHART_FONT + 1, fontWeight=500, color=MUTED
                        ),
                    )
                )
        st.markdown(
            '<div class="note">Each block copies the order of supply phases from one '
            "real stretch of the same stage that was followed by the same next stage; "
            "flows are the medians of that stretch.</div>",
            unsafe_allow_html=True,
        )
    c1, c2 = st.columns([3, 2], gap="medium")
    with c1, st.container(border=True):
        st.markdown("**Supply phases per block**")
        st.dataframe(
            ph,
            hide_index=True,
            width="stretch",
            height=480,
            column_config={
                **DT_COLS,
                "seq": "Block",
                "step": "Stage",
                "phase": "Supply",
                "duration_h": st.column_config.NumberColumn(
                    "Length (h)", format="%.2f"
                ),
                "source_episode": "Copied from",
                **{
                    c: st.column_config.NumberColumn(c, format="%.0f")
                    for c in flow_cols
                },
            },
        )
    with c2, st.container(border=True):
        st.markdown("**Real flow levels per supply phase** (median ln/min)")
        st.dataframe(
            flow_levels(),
            hide_index=True,
            width="stretch",
            height=480,
            column_config={
                "phase": "Supply",
                "minutes": st.column_config.NumberColumn("Real minutes", format="%d"),
                **{
                    c: st.column_config.NumberColumn(c, format="%.0f") for c in pg.FLOWS
                },
            },
        )
        st.markdown(
            '<div class="note">FIRC 1,1,3 is only logged from 2026-03-17 (tag renamed '
            "in the PLC).</div>",
            unsafe_allow_html=True,
        )
    with st.container(border=True):
        st.markdown(
            "**Gas rules per stage** (industry permissives — the stage is set by "
            "temperature and load, the supply must fit it)"
        )
        g = df.get("gas_check", pd.Series(dtype=str)).fillna("")
        k = st.columns(3)
        k[0].metric(
            "Blocks meeting the rules as copied", int((g == "ok").sum()), border=True
        )
        k[1].metric(
            "Blocks fixed to meet them",
            int(g.str.startswith("fixed").sum()),
            border=True,
        )
        k[2].metric(
            "Blocks still breaking a rule",
            int(g.str.endswith("not met").sum()),
            border=True,
        )
        st.dataframe(
            pd.DataFrame(pg.GAS_RULES, columns=["Rule", "Condition"]),
            hide_index=True,
            width="stretch",
        )

with t_summary:
    c1, c2 = st.columns([2, 3], gap="medium")
    with c1, st.container(border=True):
        st.markdown("**Time per stage**")
        donut = (
            alt.Chart(summary)
            .mark_arc(innerRadius=110, outerRadius=180, padAngle=0.012, cornerRadius=3)
            .encode(
                theta="total_h:Q",
                color=alt.Color(
                    "step:N", scale=scale, legend=alt.Legend(title=None, orient="right")
                ),
                tooltip=[
                    alt.Tooltip("step:N", title="Stage"),
                    alt.Tooltip("total_h:Q", title="Hours", format=".1f"),
                    alt.Tooltip("share:Q", title="Share", format=".1%"),
                ],
            )
        )
        centre = (
            alt.Chart(pd.DataFrame({"t": [f"{summary['total_h'].sum():.0f} h"]}))
            .mark_text(fontSize=32, fontWeight=600, color=INK, font=FONT)
            .encode(text="t:N")
        )
        chart((donut + centre).properties(height=420))
    with c2, st.container(border=True):
        st.markdown("**Summary per stage**")
        st.dataframe(
            summary,
            hide_index=True,
            width="stretch",
            column_config={
                "step": "Stage",
                "blocks": "Blocks",
                "total_h": st.column_config.NumberColumn("Total (h)", format="%.1f"),
                "mean_h": st.column_config.NumberColumn("Mean (h)", format="%.2f"),
                "min_h": st.column_config.NumberColumn("Min (h)", format="%.2f"),
                "max_h": st.column_config.NumberColumn("Max (h)", format="%.2f"),
                "share": st.column_config.ProgressColumn(
                    "Share", format="percent", min_value=0, max_value=1
                ),
            },
        )
    with st.container(border=True):
        st.markdown("**Blocks**")
        st.dataframe(
            df.drop(columns=["pattern", "seed"]),
            hide_index=True,
            width="stretch",
            column_config={
                **DT_COLS,
                "seq": "Block",
                "step": "Step",
                "stage": "Stage",
                "sub_stage": "Sub-stage",
                "duration_h": st.column_config.NumberColumn(
                    "Length (h)", format="%.2f"
                ),
                "phases": "Supply plan",
                "phase_source": "Supply copied from",
                "gas_check": "Gas rules",
            },
        )

# ---------------------------------------------------------------- export
section("Export")
allp = pd.concat(pats, ignore_index=True)[
    [
        "pattern",
        "seed",
        "seq",
        "step",
        "stage",
        "sub_stage",
        "start",
        "end",
        "duration_h",
        "phases",
        "phase_source",
        "gas_check",
    ]
]
with st.container(border=True):
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "This pattern (CSV)",
        df.drop(columns=["pattern"]).to_csv(index=False),
        f"pattern_{df['seed'].iat[0]}.csv",
        "text/csv",
        width="stretch",
        icon=":material/download:",
    )
    c2.download_button(
        f"All {len(pats)} patterns (CSV)",
        allp.to_csv(index=False),
        f"patterns_{st.session_state.seed}_x{len(pats)}.csv",
        "text/csv",
        width="stretch",
        icon=":material/download:",
    )
    if c3.button("Save to datasets/ folder", width="stretch", icon=":material/save:"):
        day = pg.day_dir(st.session_state.seed if len(pats) > 1 else df["seed"].iat[0])
        day.mkdir(parents=True, exist_ok=True)
        name = (
            f"pattern_{df['seed'].iat[0]}.csv"
            if len(pats) == 1
            else f"patterns_{st.session_state.seed}_x{len(pats)}.csv"
        )
        (allp if len(pats) > 1 else df.drop(columns=["pattern"])).to_csv(
            day / name, index=False
        )
        ph.to_csv(day / name.replace(".csv", "_phases.csv"), index=False)
        st.success(
            f"Saved {day / name} (+ _phases.csv of the pattern shown)",
            icon=":material/check_circle:",
        )

# ---------------------------------------------------------------- fill with real data
with t_fill:
    with st.container(border=True):
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.markdown(
            "Each block gets real sensor data from an episode of the same stage that "
            "starts at about the same stack temperature (Shut-down: real cool-downs "
            "joined part-way). Temperatures and pressures are joined smoothly between "
            "blocks; episodes whose gas / air supply matches the block's plan are "
            "preferred."
        )
        key = (
            df["seed"].iat[0],
            tuple(df["step"]),
            tuple(df["duration_h"]),
            tuple(df["phases"]),
        )
        if c2.button(
            "Fill this pattern",
            type="primary",
            icon=":material/play_arrow:",
            width="stretch",
        ):
            with st.spinner("Copying real episodes ..."):
                st.session_state.filled = (
                    key,
                    *pf.fill(df, int(df["seed"].iat[0]), real_library()),
                )
    if st.session_state.get("filled", (None,))[0] == key:
        _, syn, used_ep = st.session_state.filled
        bad = used_ep[used_ep["fit"].str.contains("outside")]
        if len(bad):
            st.warning(
                "These blocks are shorter or longer than any real episode from that "
                "temperature, so their episode was squeezed / stretched a lot: "
                + ", ".join(f"{r.seq} {r.step}" for r in bad.itertuples()),
                icon=":material/warning:",
            )
        match = (used_ep["phase_match_pct"] * used_ep["minutes"]).sum() / used_ep.loc[
            used_ep["phase_match_pct"].notna(), "minutes"
        ].sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Synthetic minutes", f"{len(syn):,}", border=True)
        m2.metric(
            "Sensors", sum(syn[c].dtype.kind == "f" for c in syn.columns), border=True
        )
        m3.metric("Planned supply matched", f"{match:.0f} %", border=True)
        m4.metric(
            "FIRC 1,1,3 coverage",
            f"{100 * syn['ct_FIRC_113_PV_ProcessValue'].notna().mean():.0f} %"
            if "ct_FIRC_113_PV_ProcessValue" in syn
            else "–",
            border=True,
            help=(
                "Only real episodes from 2026-03-17 on carry the present FIRC 1,1,3 tag"
            ),
        )
        with st.container(border=True):
            st.markdown("**Supply copied into the synthetic data**")
            copied = pd.DataFrame(
                {"t": syn.index, "phase": syn["phase"].fillna("")}
            ).iloc[::5]
            copied = copied[copied["phase"] != ""]
            chart(
                alt.Chart(copied)
                .mark_tick(thickness=4, size=60)
                .encode(
                    x=alt.X("t:T", title=None, axis=alt.Axis(labelAngle=0)),
                    color=alt.Color(
                        "phase:N",
                        scale=PH_SCALE,
                        legend=alt.Legend(title=None, orient="top"),
                    ),
                    tooltip=[
                        alt.Tooltip("t:T", title="Time", format="%Y-%m-%d %H:%M"),
                        alt.Tooltip("phase:N", title="Supply"),
                    ],
                )
                .properties(height=110)
            )
        with st.container(border=True):
            sensors = [c for c in syn.columns if syn[c].dtype.kind == "f"]
            show = st.multiselect(
                "Signals",
                sensors,
                default=[
                    c
                    for c in [
                        "T_stack_C",
                        "TIRC_2_06",
                        "PLC_hostSetp_ctrl_ctEIRC41_rCurrMonitor",
                        "ct_FIRC_111_PV_ProcessValue",
                        "ct_FIRC_13_PV_ProcessValue",
                        "ct_FIRC_113_PV_ProcessValue",
                    ]
                    if c in sensors
                ],
            )
            if show:
                steps = [
                    pg.step_name(a, "" if pd.isna(b) else b)
                    for a, b in zip(syn["stage"], syn["sub_stage"])
                ]
                blk = (pd.Series(steps) != pd.Series(steps).shift()).cumsum().to_numpy()
                plot_df = syn[show].assign(step=steps, blk=blk).iloc[::5].reset_index()
                legend([(s, COLOR[s]) for s in order])
                # one full-width chart per signal; each block is its own line segment
                for c in show:
                    chart(
                        alt.Chart(plot_df.rename(columns={c: "value"}))
                        .mark_line(strokeWidth=2)
                        .encode(
                            x=alt.X(
                                "Date Time:T", title=None, axis=alt.Axis(labelAngle=0)
                            ),
                            y=alt.Y(
                                "value:Q",
                                title=None,
                                scale=alt.Scale(zero=False),
                                axis=alt.Axis(tickCount=6),
                            ),
                            color=alt.Color("step:N", scale=scale, legend=None),
                            detail="blk:N",
                            tooltip=[
                                alt.Tooltip(
                                    "Date Time:T", title="Time", format="%Y-%m-%d %H:%M"
                                ),
                                alt.Tooltip("step:N", title="Stage"),
                                alt.Tooltip("value:Q", title=c, format=".1f"),
                            ],
                        )
                        .properties(
                            height=320,
                            title=alt.Title(
                                c, fontSize=CHART_FONT + 1, fontWeight=500, color=MUTED
                            ),
                        )
                        .interactive(bind_y=False)
                    )
        with st.container(border=True):
            st.markdown("**Real episodes used per block**")
            st.dataframe(used_ep, hide_index=True, width="stretch")
            name = f"synthetic_{df['seed'].iat[0]}"
            c1, c2 = st.columns(2)
            c1.download_button(
                "Synthetic data (CSV)",
                syn.to_csv(),
                f"{name}.csv",
                "text/csv",
                width="stretch",
                icon=":material/download:",
            )
            if c2.button(
                "Save to datasets/ folder (parquet)",
                width="stretch",
                icon=":material/save:",
            ):
                day = pf.day_folder(syn, df["seed"].iat[0])
                syn.to_parquet(day / f"{name}.parquet")
                used_ep.to_csv(day / f"{name}_blocks.csv", index=False)
                st.success(
                    f"Saved {day / name}.parquet and {name}_blocks.csv",
                    icon=":material/check_circle:",
                )
