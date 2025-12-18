import os
import sqlite3
from contextlib import closing
import streamlit as st
import folium
from streamlit_folium import st_folium

DB_PATH = "trip_plan.sqlite3"

# -------------------------
# DB (영구 저장)
# -------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with closing(get_conn()) as conn, conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            memo TEXT DEFAULT ''
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_places_day_ord ON places(day, ord)")

def fetch_places(day: int):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT id, day, ord, name, lat, lng, memo FROM places WHERE day=? ORDER BY ord ASC",
            (day,)
        ).fetchall()
    return rows

def next_ord(day: int):
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT COALESCE(MAX(ord), 0) FROM places WHERE day=?", (day,)).fetchone()
        return int(row[0]) + 1

def add_place(day: int, name: str, lat: float, lng: float, memo: str = ""):
    o = next_ord(day)
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "INSERT INTO places(day, ord, name, lat, lng, memo) VALUES(?,?,?,?,?,?)",
            (day, o, name, lat, lng, memo or "")
        )

def delete_place(place_id: int, day: int):
    with closing(get_conn()) as conn, conn:
        conn.execute("DELETE FROM places WHERE id=?", (place_id,))
        # ord 재정렬
        rows = conn.execute(
            "SELECT id FROM places WHERE day=? ORDER BY ord ASC", (day,)
        ).fetchall()
        for i, (pid,) in enumerate(rows, start=1):
            conn.execute("UPDATE places SET ord=? WHERE id=?", (i, pid))

def move_place(day: int, place_id: int, direction: str):
    """direction: 'up' or 'down'"""
    with closing(get_conn()) as conn, conn:
        rows = conn.execute(
            "SELECT id, ord FROM places WHERE day=? ORDER BY ord ASC", (day,)
        ).fetchall()
        idx = next((i for i, (pid, _) in enumerate(rows) if pid == place_id), None)
        if idx is None:
            return
        if direction == "up" and idx > 0:
            rows[idx], rows[idx-1] = rows[idx-1], rows[idx]
        elif direction == "down" and idx < len(rows) - 1:
            rows[idx], rows[idx+1] = rows[idx+1], rows[idx]
        else:
            return
        # ord 재저장
        for i, (pid, _) in enumerate(rows, start=1):
            conn.execute("UPDATE places SET ord=? WHERE id=?", (i, pid))

# -------------------------
# Google Maps directions link (대중교통)
# -------------------------
def gmaps_transit_link(origin_lat, origin_lng, dest_lat, dest_lng):
    # 구글맵 경로 안내(대중교통)
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin_lat},{origin_lng}"
        f"&destination={dest_lat},{dest_lng}"
        "&travelmode=transit"
    )

# -------------------------
# Folium Map
# -------------------------
def build_map(day: int, places):
    if places:
        avg_lat = sum(r[4] for r in places) / len(places)
        avg_lng = sum(r[5] for r in places) / len(places)
        m = folium.Map(location=[avg_lat, avg_lng], zoom_start=13)
    else:
        # 장소 없을 때 기본(서울 시청 근처)
        m = folium.Map(location=[37.5665, 126.9780], zoom_start=12)

    # 마커(순서 번호)
    for (pid, d, ord_, name, lat, lng, memo) in places:
        label = f"{ord_}. {name}"
        popup_html = f"<b>{label}</b><br/>{memo}" if memo else f"<b>{label}</b>"
        folium.Marker(
            location=[lat, lng],
            tooltip=label,
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.DivIcon(
                html=f"""
                <div style="
                    font-size: 12px;
                    background: white;
                    border: 1px solid #333;
                    border-radius: 12px;
                    padding: 2px 6px;
                    ">
                    {ord_}
                </div>
                """
            ),
        ).add_to(m)

    # 선(전체 경로)
    coords = [(r[4], r[5]) for r in places]
    if len(coords) >= 2:
        folium.PolyLine(
            coords,
            weight=5,
            opacity=0.6,
            tooltip="전체 동선",
        ).add_to(m)

        # 구간별 선(클릭 시 해당 구간 대중교통 길찾기 링크 제공)
        for i in range(len(coords) - 1):
            (a_lat, a_lng) = coords[i]
            (b_lat, b_lng) = coords[i + 1]
            link = gmaps_transit_link(a_lat, a_lng, b_lat, b_lng)
            seg_tooltip = f"구간 {i+1} → {i+2} (클릭)"
            popup = folium.Popup(
                html=f"""
                <div style="font-size: 13px;">
                  <b>{seg_tooltip}</b><br/>
                  <a href="{link}" target="_blank">구글맵(대중교통)으로 경로 보기</a>
                </div>
                """,
                max_width=300,
            )
            folium.PolyLine(
                [(a_lat, a_lng), (b_lat, b_lng)],
                weight=10,     # 클릭 잘 되게 두껍게
                opacity=0.15,  # 너무 진하지 않게
                tooltip=seg_tooltip,
                popup=popup,
            ).add_to(m)

    return m

# -------------------------
# Streamlit UI
# -------------------------
st.set_page_config(page_title="여행 일정 플래너(1~13일)", layout="wide")
init_db()

st.title("🗺️ 여행 일정 플래너 (Streamlit + Folium)")
st.caption("1~13일차 선택 → 지도에 장소/동선 표시 → 선(구간) 클릭 시 구글맵 대중교통 경로 안내로 이동")

col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    day = st.selectbox("📅 날짜(일차) 선택", list(range(1, 14)), index=0)

    st.subheader("➕ 장소 추가")
    with st.form("add_place_form", clear_on_submit=True):
        name = st.text_input("장소 이름", placeholder="예: 국립중앙박물관")
        lat = st.number_input("위도(lat)", value=37.5665, format="%.6f")
        lng = st.number_input("경도(lng)", value=126.9780, format="%.6f")
        memo = st.text_area("메모(선택)", placeholder="예: 10:00 입장 / 근처 점심 추천 등", height=80)
        submitted = st.form_submit_button("추가")
        if submitted:
            if not name.strip():
                st.error("장소 이름을 입력해줘.")
            else:
                add_place(day, name.strip(), float(lat), float(lng), memo.strip())
                st.success("추가 완료!")
                st.rerun()

    st.divider()
    st.subheader("📌 현재 선택한 날짜의 장소 목록")

    places = fetch_places(day)

    if not places:
        st.info("아직 장소가 없어. 위에서 추가해줘.")
    else:
        for (pid, d, ord_, name, plat, plng, pmemo) in places:
            c1, c2, c3, c4 = st.columns([6, 2, 2, 2])
            with c1:
                st.write(f"**{ord_}. {name}**  \n({plat:.6f}, {plng:.6f})")
                if pmemo:
                    st.caption(pmemo)
            with c2:
                if st.button("⬆️", key=f"up_{pid}"):
                    move_place(day, pid, "up")
                    st.rerun()
            with c3:
                if st.button("⬇️", key=f"down_{pid}"):
                    move_place(day, pid, "down")
                    st.rerun()
            with c4:
                if st.button("🗑️", key=f"del_{pid}"):
                    delete_place(pid, day)
                    st.rerun()

with col_right:
    st.subheader(f"🗺️ {day}일차 지도")
    places = fetch_places(day)
    m = build_map(day, places)

    # folium 렌더
    # returned["last_object_clicked"] 등으로 확장 가능(마커 클릭 정보 활용)
    st_folium(m, width=950, height=650)

st.caption("저장은 로컬 SQLite 파일(trip_plan.sqlite3)에 기록돼서 코드 수정/새로고침 후에도 유지됩니다.")
