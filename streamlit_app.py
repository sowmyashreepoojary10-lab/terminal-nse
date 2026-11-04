"""
NSE Stock Dashboard — Streamlit front end (free hosting on Streamlit Community Cloud)

It imports the analysis functions straight from nse_analysis_api.py, so you do NOT
need to host the FastAPI service separately for this dashboard. Keep both files
in the same GitHub repo.

Run locally:  streamlit run streamlit_app.py
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import nse_analysis_api as api

st.set_page_config(page_title="NSE Stock Dashboard", page_icon="📈", layout="wide")

VERDICT_STYLE = {
    "bullish": ("🟢 Bullish", "green"),
    "neutral": ("🟡 Neutral", "orange"),
    "bearish": ("🔴 Bearish", "red"),
    "insufficient_data": ("⚪ Insufficient data", "gray"),
}

# ── sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("📈 NSE Dashboard")
months = st.sidebar.slider("Chart history (months)", 1, 24, 6)
refresh = st.sidebar.checkbox("Bypass cache (fetch fresh data)", value=False)
st.sidebar.caption(api.DISCLAIMER)


# ── chart ────────────────────────────────────────────────────────────────────
def build_chart(hist: pd.DataFrame, ticker: str, months: int) -> go.Figure:
    close = hist["Close"]
    rsi = api.calculate_rsi(close)
    macd_line, signal_line, macd_hist = api.calculate_macd(close)
    ma50, ma200 = api.calculate_moving_averages(close)

    n = months * 21
    d = hist.tail(n)
    sl = lambda s: s.tail(n)

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=(f"{ticker} price", "RSI (14)", "MACD"),
    )
    fig.add_trace(go.Candlestick(
        x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="Price"), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=sl(ma50), name="MA 50", line=dict(width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=sl(ma200), name="MA 200", line=dict(width=1.5)), row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=sl(rsi), name="RSI", line=dict(width=1.5)), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)

    fig.add_trace(go.Bar(x=d.index, y=sl(macd_hist), name="Histogram", opacity=0.5), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=sl(macd_line), name="MACD", line=dict(width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=sl(signal_line), name="Signal", line=dict(width=1.5)), row=3, col=1)

    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    fig.update_layout(height=760, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.04))
    return fig


# ── tabs ─────────────────────────────────────────────────────────────────────
tab_analysis, tab_watch = st.tabs(["Analysis", "Watchlist"])

with tab_analysis:
    with st.form("symbol_form"):
        c1, c2 = st.columns([4, 1])
        symbol = c1.text_input("NSE symbol", value="RELIANCE",
                               help="Example: RELIANCE, TCS, INFY, HDFCBANK")
        submitted = c2.form_submit_button("Analyze", use_container_width=True)

    if submitted or symbol:
        ticker = api.normalize_ticker(symbol)
        try:
            with st.spinner(f"Analyzing {ticker}..."):
                analysis = api.build_analysis(ticker, refresh)
                sig = api.score_signal(analysis["technical"], analysis["fundamentals"])
                hist = api.get_history(ticker, False)  # already cached by build_analysis
        except Exception:
            st.error(f"No data found for {ticker}. Check the symbol and try again.")
            st.stop()

        t, f = analysis["technical"], analysis["fundamentals"]
        label, color = VERDICT_STYLE.get(sig["verdict"], VERDICT_STYLE["insufficient_data"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Price (₹)", t["current_price"])
        m2.markdown(f"**Verdict**\n\n### :{color}[{label}]")
        m3.metric("Score", f"{sig['score']} / {sig['max_score']}",
                  f"{sig['score_pct']}%" if sig["score_pct"] is not None else None)
        m4.metric("Data as of", analysis["as_of"])

        if analysis["corporate_action_flag"]:
            st.warning(analysis["corporate_action_note"])

        st.plotly_chart(build_chart(hist, ticker, months), use_container_width=True)

        left, right = st.columns(2)
        with left:
            st.subheader("Why this verdict")
            st.caption(f"Technical {sig['technical_score']} · Fundamental {sig['fundamental_score']}")
            reasons = pd.DataFrame(sig["reasons"])
            if not reasons.empty:
                st.dataframe(reasons, hide_index=True, use_container_width=True)
        with right:
            st.subheader("Fundamentals")
            fund_df = pd.DataFrame(
                [(k, v) for k, v in f.items() if not k.endswith("_quarter")],
                columns=["metric", "value"],
            )
            fund_df["value"] = fund_df["value"].astype(str)
            st.dataframe(fund_df, hide_index=True, use_container_width=True)
            if f.get("margin_basis") == "ttm":
                st.caption("Margins and ROE use trailing four quarters (TTM).")

        with st.expander("All technical indicators"):
            tech_df = pd.DataFrame(list(t.items()), columns=["indicator", "value"])
            tech_df["value"] = tech_df["value"].astype(str)
            st.dataframe(tech_df, hide_index=True, use_container_width=True)

with tab_watch:
    raw = st.text_area("Symbols (comma-separated, max 10)",
                       value="RELIANCE, TCS, INFY, HDFCBANK, ITC")
    if st.button("Load watchlist"):
        symbols = [s.strip() for s in raw.split(",") if s.strip()][:10]
        rows = []
        progress = st.progress(0.0)
        for i, s in enumerate(symbols):
            tk = api.normalize_ticker(s)
            try:
                h = api.get_history(tk, refresh)
                if h.empty:
                    rows.append({"symbol": tk, "note": "No data"})
                else:
                    snap, flag = api.get_technical_snapshot(h)
                    rows.append({
                        "symbol": tk,
                        "price": snap["current_price"],
                        "rsi_14": snap["rsi_14"],
                        "macd_hist": snap["macd_histogram"],
                        "ma_trend": snap["ma_trend"],
                        "% of 52w high": snap["pct_of_52w_high"],
                        "as_of": str(h.index[-1].date()),
                        "corp_action_flag": flag,
                    })
            except Exception:
                rows.append({"symbol": tk, "note": "Failed to fetch"})
            progress.progress((i + 1) / len(symbols))
        progress.empty()
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
