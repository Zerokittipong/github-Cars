import dash
from dash import html, dcc
import pandas as pd
import plotly.express as px
from fleet.db import SessionLocal
from fleet.models import UsageLog  # ใช้เฉพาะ Usage ก่อน

dash.register_page(__name__, path="/", name="Dashboard")

def layout():
    fig_usage = px.scatter(title="ยังไม่มีข้อมูลการเบิก")

    with SessionLocal() as s:
        usage = s.query(UsageLog).all()
        if usage:
            udf = pd.DataFrame([{
                "borrower": (u.borrower.full_name if u.borrower else "unknown")
            } for u in usage])
            fig_usage = px.histogram(udf, x="borrower", title="จำนวนครั้งการเบิกตามผู้เบิก")

    return html.Div([
        html.H2("Dashboard"),
        dcc.Graph(figure=fig_usage),
    ])
