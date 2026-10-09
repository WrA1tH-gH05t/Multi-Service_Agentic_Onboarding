from app.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path') and r.path]
print(f"Total routes: {len(routes)}")
for r in sorted(routes):
    print(f"  {r}")
