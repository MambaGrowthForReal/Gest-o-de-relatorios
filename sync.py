import os
import time
import json
import requests
from datetime import datetime, timezone

# ── Configurações ──────────────────────────────────────────
CLICKUP_TOKEN = os.getenv("CLICKUP_TOKEN", "pk_206504924_97P74AJM8PTO06YGY0P17EXV366HV81N")
SUPABASE_URL  = os.getenv("SUPABASE_URL",  "https://wlfrmnpntpnbjekwnvcs.supabase.co")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY",  "sb_secret_r7ZC2OnfvL7NCKsm_nSrIA_c6oS7BOZ")

POLL_INTERVAL_HOURS = 6
NOVOS_CRIATIVOS_LIST_ID = "901700896208"

CLICKUP_HEADERS  = {"Authorization": CLICKUP_TOKEN}
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

# ── Helpers ClickUp ────────────────────────────────────────

def get_teams():
    r = requests.get("https://api.clickup.com/api/v2/team", headers=CLICKUP_HEADERS)
    r.raise_for_status()
    return r.json().get("teams", [])

def get_spaces(team_id):
    r = requests.get(f"https://api.clickup.com/api/v2/team/{team_id}/space?archived=false", headers=CLICKUP_HEADERS)
    r.raise_for_status()
    return r.json().get("spaces", [])

def get_folders(space_id):
    r = requests.get(f"https://api.clickup.com/api/v2/space/{space_id}/folder?archived=false", headers=CLICKUP_HEADERS)
    r.raise_for_status()
    return r.json().get("folders", [])

def get_folderless_lists(space_id):
    r = requests.get(f"https://api.clickup.com/api/v2/space/{space_id}/list?archived=false", headers=CLICKUP_HEADERS)
    r.raise_for_status()
    return r.json().get("lists", [])

def get_lists_in_folder(folder_id):
    r = requests.get(f"https://api.clickup.com/api/v2/folder/{folder_id}/list?archived=false", headers=CLICKUP_HEADERS)
    r.raise_for_status()
    return r.json().get("lists", [])

def get_tasks_in_list(list_id, page=0):
    params = {
        "archived": "false",
        "include_closed": "true",
        "page": page,
        "order_by": "updated",
        "reverse": "true",
    }
    r = requests.get(f"https://api.clickup.com/api/v2/list/{list_id}/task", headers=CLICKUP_HEADERS, params=params)
    r.raise_for_status()
    data = r.json()
    return data.get("tasks", []), data.get("last_page", True)

def get_task_detail(task_id):
    r = requests.get(f"https://api.clickup.com/api/v2/task/{task_id}", headers=CLICKUP_HEADERS)
    r.raise_for_status()
    return r.json()

# ── Parser de tarefa ───────────────────────────────────────

def parse_task(task, space_id, space_name, list_id, list_name):
    assignees = [{"id": a["id"], "username": a.get("username", ""), "email": a.get("email", "")} for a in task.get("assignees", [])]

    def ts(ms):
        if not ms:
            return None
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()

    return {
        "id":           task["id"],
        "name":         task.get("name", ""),
        "status":       task.get("status", {}).get("status", ""),
        "assignees":    json.dumps(assignees),
        "space_id":     space_id,
        "space_name":   space_name,
        "list_id":      list_id,
        "list_name":    list_name,
        "due_date":     ts(task.get("due_date")),
        "date_created": ts(task.get("date_created")),
        "date_updated": ts(task.get("date_updated")),
        "synced_at":    datetime.now(tz=timezone.utc).isoformat(),
    }

# ── Supabase upsert ────────────────────────────────────────

def upsert_tasks(tasks):
    if not tasks:
        return
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/tasks",
        headers=SUPABASE_HEADERS,
        json=tasks,
    )
    if r.status_code not in (200, 201):
        print(f"  ⚠️  Erro no upsert: {r.status_code} {r.text[:200]}")
    else:
        print(f"  ✅ {len(tasks)} tarefa(s) sincronizada(s)")

# ── Sync especial: Novos criativos com due_date individual ─

def sync_novos_criativos():
    print("  🎯 Sync especial: Novos criativos (due_date individual para todas)")
    page = 0
    total = 0
    recuperados = 0

    while True:
        tasks_raw, last_page = get_tasks_in_list(NOVOS_CRIATIVOS_LIST_ID, page)
        parsed = []

        for t in tasks_raw:
            p = parse_task(t, "", "Tráfego", NOVOS_CRIATIVOS_LIST_ID, "Novos criativos")

            # Se due_date vier null, busca individualmente
            if p["due_date"] is None:
                try:
                    detail = get_task_detail(t["id"])
                    ms = detail.get("due_date")
                    if ms:
                        p["due_date"] = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
                        recuperados += 1
                        print(f"  📅 {t.get('name', '')[:50]} → {p['due_date'][:10]}")
                    time.sleep(0.3)
                except Exception as e:
                    print(f"  ⚠️  Erro task {t['id']}: {e}")

            parsed.append(p)

        if parsed:
            upsert_tasks(parsed)
            total += len(parsed)

        if last_page or not tasks_raw:
            break
        page += 1
        time.sleep(0.5)

    print(f"  ✅ Novos criativos: {total} tasks | {recuperados} due_dates recuperados")

# ── Full sync ──────────────────────────────────────────────

def full_sync():
    print(f"\n🔄 Iniciando sync — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    teams = get_teams()
    total = 0

    # Sync especial para Novos criativos primeiro
    sync_novos_criativos()

    for team in teams:
        spaces = get_spaces(team["id"])
        for space in spaces:
            sid, sname = space["id"], space["name"]
            lists = get_folderless_lists(sid)
            for folder in get_folders(sid):
                lists += get_lists_in_folder(folder["id"])

            for lst in lists:
                lid, lname = lst["id"], lst["name"]
                page = 0
                while True:
                    tasks_raw, last_page = get_tasks_in_list(lid, page)
                    parsed = [parse_task(t, sid, sname, lid, lname) for t in tasks_raw]
                    upsert_tasks(parsed)
                    total += len(parsed)
                    if last_page or not tasks_raw:
                        break
                    page += 1
                    time.sleep(0.5)

    print(f"✅ Sync completo — {total} tarefas processadas\n")

# ── Loop principal ─────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 ClickUp Sync iniciado")
    while True:
        try:
            full_sync()
        except Exception as e:
            print(f"❌ Erro no sync: {e}")
        print(f"⏳ Próximo sync em {POLL_INTERVAL_HOURS}h...")
        time.sleep(POLL_INTERVAL_HOURS * 3600)
