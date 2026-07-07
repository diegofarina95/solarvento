"""Sync del blog a prod SIN arrastrar borradores (para ejecutar a mano).

El botón «Sincronizar con prod» del portal copia public/blog tal cual, con
páginas de borrador incluidas; este script aparta los borradores, regenera,
sincroniza y los restaura — la misma secuencia que publish_group pero solo
para el sync. Uso:

    cd backend && PYTHONPATH=. .venv/bin/python ../scripts/sync-blog-limpio.py
"""
import shutil

from app import portal

refs = sorted(portal.draft_refs())
print("borradores a apartar:", refs)
aside = []
for ref in refs:
    lang, stem = portal.parse_ref(ref)
    src = portal.content_path(lang, stem)
    slug = portal.public_slug(src)
    dst = portal.DRAFTS_ASIDE / src.relative_to(portal.CONTENT_BLOG)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    aside.append((src, dst))
    shutil.rmtree(portal.generated_page(lang, slug).parent, ignore_errors=True)
try:
    ok, out = portal.run_generate()
    assert ok, f"generador: {out}"
    synced, sync_out = portal.sync_to_prod()
    assert synced, f"sync: {sync_out}"
    print("sync a prod OK")
finally:
    for src, dst in aside:
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
    shutil.rmtree(portal.DRAFTS_ASIDE, ignore_errors=True)
    portal.run_generate()
    print("borradores restaurados")
