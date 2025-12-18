import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

API_URL = st.secrets["API_URL"]

def api_get_all() -> pd.DataFrame:
    r = requests.get(API_URL, timeout=15)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("ok") is False:
        raise RuntimeError(data.get("error", "Unknown API error"))
    df = pd.DataFrame(data)
    if df.empty:
        return df
    # 타입 정리
    df["day"] = pd.to_numeric(df["day"], errors="coerce").astype("Int64")
    df["ord"] = pd.to_numeric(df.get("ord"), errors="coerce").fillna(0).astype(int)
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["id"] = df["id"].astype(str)
    return df

def api_post(payload: dict):
    r = requests.post(API_URL, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("ok") is False:
        raise RuntimeError(data.get("error", "Unknown API error"))
    return data

def gmaps_transit_link(a_lat, a_lon, b_lat, b_lon):
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={a_lat},{a_lon}"
        f"&destination={b_lat},{b_lon}"
        "&travelmode=transit"
    )

def build_map(day_df: pd.DataFrame):
    if day_df.empty:
        return folium.Map(location=[37.5665, 126.9780], zoom_start=12)

    day_df = day_df.sort_values("ord").reset_index(drop=True)
    m = folium.Map(location=[day_df["lat"].mean(), day_df["lon"].mean()], zoom_start=13)

    coords = []
    for i, row in day_df.iterrows():
        coords.append((row["lat"], row["lon"]))
        label = f'{int(row["ord"])}. {row["name"]}'
        folium.Marker(
            [row["lat"], row["lon"]],
            tooltip=label,
        ).add_to(m)

    if len(coords) >= 2:
        # 전체 동선
        folium.PolyLine(coords, weight=5, opacity=0.6, tooltip="전체 동선").add_to(m)

        # 구간별(클릭하면 구글맵 대중교통 링크)
        for i in range(len(coords) - 1):
            a = coords[i]
            b = coords[i + 1]
            link = gmaps_transit_link(a[0], a[1], b[0], b[1])
            popup = folium.Popup(
                html=f'<a href="{link}" target="_blank">구글맵(대중교통)으로 이 구간 경로 보기</a>',
                max_width=300,
            )
            folium.PolyLine(
                [a, b],
                weight=10,
                opacity=0.15,  # 클릭 영역은 넓게, 보이는 건 연하게
                tooltip=f"구간 {i+1} → {i+2} (클릭)",
                popup=popup,
            ).add_to(m)

    return m

st.set_page_config(page_title="여행 플래너 (Google Sheet)", layout="wide")
st.title("🗺️ 여행 일정 플래너 (Google Sheet 기반, 무료/영구저장)")
st.caption("Google Apps Script 웹앱(API) + Google Sheet 저장. 새로고침/재배포해도 데이터 유지.")

left, right = st.columns([1, 2], gap="large")

with left:
    day = st.selectbox("일차 선택", list(range(1, 14)), index=0)

    st.subheader("➕ 장소 추가")
    with st.form("add_form", clear_on_submit=True):
        name = st.text_input("장소 이름", placeholder="예: 바츨라프 광장")
        lat = st.number_input("위도(lat)", format="%.6f", value=37.5665)
        lon = st.number_input("경도(lon)", format="%.6f", value=126.9780)
        add_btn = st.form_submit_button("추가")
        if add_btn:
            if not name.strip():
                st.error("장소 이름을 입력해줘.")
            else:
                api_post({"action": "add", "day": day, "name": name.strip(), "lat": float(lat), "lon": float(lon)})
                st.success("추가 완료!")
                st.rerun()

    st.divider()
    st.subheader("📌 오늘(선택한 일차) 장소 목록")

    try:
        df = api_get_all()
    except Exception as e:
        st.error(f"데이터를 불러오지 못했어: {e}")
        st.stop()

    if df.empty:
        st.info("아직 데이터가 없어. 위에서 추가해줘.")
        day_df = df
    else:
        day_df = df[df["day"] == day].sort_values("ord").reset_index(drop=True)
        if day_df.empty:
            st.info("이 일차에는 아직 장소가 없어.")
        else:
            for _, row in day_df.iterrows():
                c1, c2, c3, c4 = st.columns([6, 2, 2, 2])
                with c1:
                    st.write(f'**{int(row["ord"])}. {row["name"]}**  \n({row["lat"]:.6f}, {row["lon"]:.6f})')
                with c2:
                    if st.button("⬆️", key=f'up_{row["id"]}'):
                        api_post({"action": "move", "day": day, "id": row["id"], "dir": "up"})
                        st.rerun()
                with c3:
                    if st.button("⬇️", key=f'down_{row["id"]}'):
                        api_post({"action": "move", "day": day, "id": row["id"], "dir": "down"})
                        st.rerun()
                with c4:
                    if st.button("🗑️", key=f'del_{row["id"]}'):
                        api_post({"action": "delete", "day": day, "id": row["id"]})
                        st.rerun()

with right:
    st.subheader(f"🗺️ {day}일차 지도")
    m = build_map(day_df)
    st_folium(m, height=650, use_container_width=True)
