import pytest

from app.routers import translation as tr

FAKE_EXTRACTION = {"Bonjour.", "Merci.", "Au revoir."}
HTML_FR = (
    "<h2>Bonjour.</h2><p>Merci a tous.</p>"
    "<span translate=\"no\">AutoPrestige</span>"
)


@pytest.fixture(autouse=True)
def _clear_translate_limits():
    tr._translate_rate_limits.clear()
    tr._char_usage.clear()
    yield
    tr._translate_rate_limits.clear()
    tr._char_usage.clear()


async def test_translate_batch(client, monkeypatch):
    async def fake_translate_texts(texts, target_lang):
        return [f"[{target_lang}]{texts[0]}", f"[{target_lang}]{texts[1]}"]

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    resp = await client.post(
        "/api/translate",
        json={"texts": ["Bonjour.", "Merci."], "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["translations"] == ["[EN]Bonjour.", "[EN]Merci."]


async def test_translate_html_nodes(client, monkeypatch):
    async def fake_translate_texts(texts, target_lang):
        mapping = {"Bonjour.": "Hello.", "Merci a tous.": "Thanks everyone."}
        return [mapping[t] for t in texts]

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    resp = await client.post(
        "/api/translate/html",
        json={"html": HTML_FR, "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    assert "Hello." in html
    assert "Thanks everyone." in html
    # Le bloc translate="no" reste intact (pas envoyé à la traduction).
    assert 'translate="no">AutoPrestige</span>' in html


async def test_translate_html_noop_when_translation_unchanged(client, monkeypatch):
    async def fake_translate_texts(texts, target_lang):
        return list(texts)  # aucune modification

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    resp = await client.post(
        "/api/translate/html",
        json={"html": HTML_FR, "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["html"] == HTML_FR


async def test_translate_invalid_target(client):
    resp = await client.post(
        "/api/translate",
        json={"texts": ["Bonjour."], "target_lang": "XX"},
    )
    assert resp.status_code == 422


async def test_translate_html_translate_no_is_ignored(client, monkeypatch):
    sent = []

    async def fake_translate_texts(texts, target_lang):
        sent.extend(texts)
        return [f"EN:{t}" for t in texts]

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    resp = await client.post(
        "/api/translate/html",
        json={
            "html": '<div>Traduis-moi.</div><span translate="no">Garder.</span>',
            "target_lang": "EN",
        },
    )
    assert resp.status_code == 200, resp.text
    assert sent == ["Traduis-moi."]
    assert "EN:Traduis-moi." in resp.json()["html"]
    assert "Garder." in resp.json()["html"]


class _FakeGoogleResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeGoogleClient:
    """Remplace httpx.AsyncClient : post() renvoie la réponse simulée."""

    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        return _FakeGoogleResp(self._payload)


async def test_single_multiline_phrase_returns_whole_block(client, monkeypatch):
    """Une phrase multi-lignes ne doit PAS être découpée (régression 502)."""
    source = "\nUn processus clair en 3 étapes pour trouver et recevoir votre\nvéhicule idéal.\n"
    google_reply = "A clear 3-step process to find and receive your\nideal vehicle."
    fake = _FakeGoogleClient([google_reply, "fr", "en"])
    monkeypatch.setattr(tr.httpx, "AsyncClient", lambda *a, **k: fake)

    out = await tr._translate_google_free_batch([source], "EN")
    assert out == [google_reply]
    assert out[0] == google_reply  # le bloc entier, pas un découpage par lignes


async def test_multi_phrase_batch_still_split_by_lines(client, monkeypatch):
    """Un lot de phrases SANS retour à la ligne garde le découpage par \\n."""
    google_reply = "Hello world\nHow are you?"
    fake = _FakeGoogleClient([google_reply, "fr", "en"])
    monkeypatch.setattr(tr.httpx, "AsyncClient", lambda *a, **k: fake)

    out = await tr._translate_google_free_batch(["Bonjour.", "Comment allez-vous ?"], "EN")
    assert out == ["Hello world", "How are you?"]


async def test_translate_html_with_multiline_text_no_502(client, monkeypatch):
    """L'endpoint HTML avec un nœud texte multi-lignes doit répondre 200."""
    source = "Véhicules neufs et\nsélectionnés avec soin"
    google_reply = "New vehicles\ncarefully selected"
    fake = _FakeGoogleClient([google_reply, "fr", "en"])
    monkeypatch.setattr(tr.httpx, "AsyncClient", lambda *a, **k: fake)

    resp = await client.post(
        "/api/translate/html",
        json={"html": f"<p>{source}</p>", "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    assert "New vehicles" in html
    assert "carefully selected" in html


# ── Réinjection par parseur (attributs, textarea, entités) ──────────────


async def test_translate_html_preserves_attribute_values(client, monkeypatch):
    """Un texte identique dans un attribut et un nœud texte : seul le NŒUD
    TEXTE est traduit (le str.replace historique traduisait l'attribut et
    laissait le texte en français)."""

    async def fake_translate_texts(texts, target_lang):
        mapping = {"Voir les détails": "See details"}
        return [mapping[t] for t in texts]

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    resp = await client.post(
        "/api/translate/html",
        json={"html": '<a title="Voir les détails" href="/v">Voir les détails</a>', "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]
    assert 'title="Voir les détails"' in html  # attribut intact
    assert ">See details<" in html             # texte traduit


async def test_translate_html_textarea_content_is_never_translated(client, monkeypatch):
    """Le contenu d'un <textarea> est une VALEUR saisie par l'utilisateur :
    il ne doit être ni extrait, ni traduit (aligne le backend sur le front)."""
    sent = []

    async def fake_translate_texts(texts, target_lang):
        sent.extend(texts)
        return [f"EN:{t}" for t in texts]

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    resp = await client.post(
        "/api/translate/html",
        json={"html": "<p>Traduis-moi.</p><textarea>Ne pas traduire</textarea>", "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    assert sent == ["Traduis-moi."]
    html = resp.json()["html"]
    assert "EN:Traduis-moi." in html
    assert "<textarea>Ne pas traduire</textarea>" in html


async def test_translate_html_matches_entity_encoded_text(client, monkeypatch):
    """Un texte porteur d'entités (&amp;) doit être trouvé et traduit — la
    réponse rééchappe correctement les caractères spéciaux."""

    async def fake_translate_texts(texts, target_lang):
        mapping = {"Essai & démo gratuite": "Test & free demo"}
        return [mapping[t] for t in texts]

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    resp = await client.post(
        "/api/translate/html",
        json={"html": "<p>Essai &amp; démo gratuite</p>", "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    assert "<p>Test &amp; free demo</p>" in resp.json()["html"]


async def test_translate_html_keeps_untranslated_markup_verbatim(client, monkeypatch):
    """Le markup non traduit doit ressortir à l'identique (attributs, ordre,
    entités) : seule la traduction des nœuds texte est rééchappée."""

    async def fake_translate_texts(texts, target_lang):
        return list(texts)  # aucune traduction

    monkeypatch.setattr(tr, "_translate_texts", fake_translate_texts)

    html = '<div class="a" data-x="1">Bonjour.</div><!-- commentaire -->'
    resp = await client.post(
        "/api/translate/html",
        json={"html": html, "target_lang": "EN"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["html"] == html
