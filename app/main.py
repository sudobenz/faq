import csv
from collections import Counter
import hashlib
import hmac
from html import escape, unescape
from datetime import datetime, timedelta, timezone
import io
import json
import os
import re
import secrets
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, urlparse, urljoin

import bleach
from authlib.integrations.base_client import OAuthError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, desc, func, or_
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .auth import get_user, hash_password, is_admin, local_auth_enabled, oauth, oidc_configured, verify_password
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import AppSetting, Article, ArticleFollow, AnalyticsEvent, LocalAccount, Question, CmsPage, ContentRevision, DocumentAsset

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENT_DIR = BASE_DIR / "private_documents"
DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name, version="0.8.4")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.environment == "production",
    session_cookie="faq_session",
    max_age=60 * 60 * 8,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union({
    "p", "h1", "h2", "h3", "h4", "br", "hr", "img", "figure", "figcaption",
    "table", "thead", "tbody", "tr", "th", "td", "div", "span", "pre", "code",
    "blockquote", "u", "s", "del", "iframe"
})
ALLOWED_ATTRS = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "*": ["class", "style", "data-checked", "data-list"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "iframe": ["src", "title", "width", "height", "allow", "allowfullscreen"],
    "td": ["colspan", "rowspan"], "th": ["colspan", "rowspan"],
}
ALLOWED_PROTOCOLS = {"http", "https", "mailto"}


def clean_html(value: str) -> str:
    return bleach.clean(value or "", tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
                        protocols=ALLOWED_PROTOCOLS, strip=True)


def css_rgba(hex_color: str, opacity_percent: int | str) -> str:
    """Convertit une couleur hexadécimale validée en rgba CSS."""
    color = hex_color if re.fullmatch(r"#[0-9a-fA-F]{6}", str(hex_color or "")) else "#ffffff"
    try:
        alpha = max(0, min(100, int(opacity_percent))) / 100
    except (TypeError, ValueError):
        alpha = 0.0
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    return f"rgba({red},{green},{blue},{alpha:.3f})"


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[àáâãäå]", "a", value)
    value = re.sub(r"[èéêë]", "e", value)
    value = re.sub(r"[ìíîï]", "i", value)
    value = re.sub(r"[òóôõö]", "o", value)
    value = re.sub(r"[ùúûü]", "u", value)
    value = re.sub(r"[ç]", "c", value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:230] or "article"


def settings_dict(db: Session) -> dict:
    values = {row.key: row.value for row in db.query(AppSetting).all()}
    defaults = {
        # Identité
        "brand_name": settings.app_name, "brand_tagline": "Les réponses utiles, simplement.",
        "brand_color": "#477cbd", "brand_logo_url": "", "header_subtitle": "ESPACE RESSOURCES",
        "footer_text": "Centre d'aide — Base de connaissances", "footer_secondary_text": "Une base de connaissances évolutive",
        "footer_secondary_url": "/analytics/preferences",
        # Navigation et recherche
        "search_placeholder": "Rechercher un article, une procédure, une réponse…", "search_button_label": "Rechercher",
        "oidc_button_label": settings.oidc_button_label, "local_button_label": "Compte local", "logout_button_label": "Déconnexion",
        "my_follows_nav_label": "Mes fiches", "my_questions_nav_label": "Mes questions",
        "nav_items": json.dumps([
            {"label": "Accueil", "url": "/"},
            {"label": "Support informatique", "url": "/?category=Informatique"},
            {"label": "Ressources métiers", "url": "/?category=M%C3%A9tiers"},
            {"label": "Poser une question", "url": "/questions/nouvelle"},
        ], ensure_ascii=False),
        "quick_links": json.dumps([
            {"label": "Support informatique", "url": "/?category=Informatique", "icon": "⌘"},
            {"label": "Procédures métiers", "url": "/?category=M%C3%A9tiers", "icon": "▤"},
            {"label": "Contacter un support", "url": "/questions/nouvelle", "icon": "✉"},
            {"label": "Suivre mes demandes", "url": "/mes-questions", "icon": "◷"},
        ], ensure_ascii=False),
        # Page d'accueil
        "home_welcome": "Bonjour et bienvenue sur", "home_featured_label": "À LA UNE",
        "home_featured_cta": "Consulter la fiche", "home_empty_title": "Les bonnes réponses, au bon endroit.",
        "home_empty_text": "Des guides courts et des procédures pour gagner du temps au quotidien.",
        "home_quick_access_title": "Accès rapides", "home_section_eyebrow": "BASE DE CONNAISSANCES",
        "home_section_title": "Fiches pratiques et tutoriels", "home_popular_title": "Les fiches les plus consultées",
        "home_question_eyebrow": "VOUS NE TROUVEZ PAS LA RÉPONSE ?",
        "home_question_title": "Une question reste sans réponse ?",
        "home_question_body": "Transmettez votre demande à l'équipe métier ou au support informatique. La connexion entreprise est requise.",
        "home_question_button": "Poser une question", "home_custom_html": "",
        # Pages FAQ et questions
        "article_follow_title": "Garder cette fiche sous la main",
        "article_follow_body": "Suivez-la pour la retrouver depuis votre espace personnel.",
        "article_follow_button": "Suivre cette fiche", "article_unfollow_button": "Ne plus suivre",
        "article_help_title": "Vous n'avez pas trouvé la réponse ?",
        "article_help_body": "Adressez une question au support ou à l'équipe métier.",
        "article_help_button": "Poser une question", "article_related_title": "Dans la même catégorie",
        "article_suggestion_button": "Faire une suggestion",
        "question_page_kicker": "CONTACT SUPPORT / MÉTIER", "question_page_title": "Poser une question",
        "question_page_body": "Décrivez votre besoin avec suffisamment de détails pour permettre à l'équipe concernée de vous répondre efficacement.",
        "question_title_label": "Objet de la question", "question_body_label": "Description",
        "question_submit_button": "Envoyer la question", "question_cancel_button": "Annuler",
        "question_privacy_note": "Ne transmettez pas de mot de passe ni de donnée personnelle sensible.",
        "user_area_eyebrow": "ESPACE UTILISATEUR", "my_questions_title": "Mes questions",
        "my_questions_intro": "Suivi des demandes transmises au support.", "my_questions_new_button": "Nouvelle question",
        "my_questions_empty_title": "Aucune question pour le moment", "my_questions_empty_text": "Vos demandes apparaîtront ici après leur envoi.",
        "my_follows_title": "Mes fiches suivies", "my_follows_intro": "Retrouvez ici les procédures que vous avez choisi de suivre.",
        "my_follows_empty_title": "Aucune fiche suivie", "my_follows_empty_text": "Ouvrez une fiche FAQ et sélectionnez « Suivre cette fiche » pour la retrouver ici.",
        "my_follows_open_button": "Explorer la FAQ", "my_follows_list_button": "Parcourir les fiches",
        "login_title": "Connexion locale", "login_intro": "Utilisez le compte administrateur local du portail FAQ.",
        "login_username_label": "Identifiant", "login_password_label": "Mot de passe", "login_submit_button": "Se connecter",
        "article_feedback_title": "Cette fiche vous a-t-elle aidé ?", "article_feedback_body": "Votre retour permettra d'améliorer les contenus.",
        "article_help_eyebrow": "BESOIN D'AIDE ?",
        # Apparence
        "secondary_color": "#53648f", "accent_red": "#c83227",
        "hero_gradient_start": "#53648f", "hero_gradient_mid": "#68465f", "hero_gradient_end": "#a33131",
        "page_background": "#ffffff", "surface_color": "#ffffff", "text_color": "#18243a",
        "hero_background_image": "", "page_background_image": "",
        "hero_overlay_color": "#1e2a41", "hero_overlay_opacity": "42",
        "hero_image_size": "cover", "hero_image_position_x": "50", "hero_image_position_y": "50", "hero_image_repeat": "no-repeat",
        "hero_padding_top": "22", "hero_padding_bottom": "16", "hero_min_height": "0",
        "hero_shape_enabled": "false", "hero_shape_height": "70",
        "page_overlay_color": "#ffffff", "page_overlay_opacity": "84",
        "page_image_size": "cover", "page_image_position_x": "50", "page_image_position_y": "50",
        "page_image_repeat": "no-repeat", "page_image_attachment": "fixed",
        "font_family": "DM Sans", "font_file_url": "", "font_file_name": "", "content_max_width": "1290", "cards_per_row": "5", "card_radius": "11",
        # Options d'affichage
        "show_nav": "true", "show_search": "true", "show_hero": "true", "show_quick_links": "true",
        "show_categories": "true", "show_popular": "true", "show_question_cta": "true",
        "show_article_views": "true", "show_article_follow": "true", "show_related_articles": "true",
        "show_article_feedback": "true", "show_footer_secondary": "true",
    }
    defaults.update(values)
    bool_keys = {k for k in defaults if k.startswith("show_")}
    for key in bool_keys:
        defaults[key] = str(defaults.get(key, "true")).strip().lower() in {"1", "true", "yes", "on", "oui"}
    numeric_settings = [
        ("content_max_width", 1290, 900, 1800), ("cards_per_row", 5, 2, 6), ("card_radius", 11, 0, 28),
        ("hero_overlay_opacity", 42, 0, 100), ("hero_image_position_x", 50, 0, 100),
        ("hero_image_position_y", 50, 0, 100), ("hero_padding_top", 22, 0, 160),
        ("hero_padding_bottom", 16, 0, 160), ("hero_min_height", 0, 0, 900),
        ("hero_shape_height", 70, 0, 180), ("page_overlay_opacity", 84, 0, 100),
        ("page_image_position_x", 50, 0, 100), ("page_image_position_y", 50, 0, 100),
    ]
    for key, fallback, low, high in numeric_settings:
        try:
            defaults[key] = max(low, min(high, int(defaults.get(key, fallback))))
        except (TypeError, ValueError):
            defaults[key] = fallback
    # Les couleurs sont limitées à des valeurs hexadécimales pour éviter toute injection CSS.
    color_keys = (
        "brand_color", "secondary_color", "accent_red", "hero_gradient_start", "hero_gradient_mid", "hero_gradient_end",
        "page_background", "surface_color", "text_color", "hero_overlay_color", "page_overlay_color",
    )
    for key in color_keys:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(defaults.get(key, ""))):
            defaults[key] = "#477cbd" if key not in {"page_overlay_color"} else "#ffffff"
    enum_settings = {
        "hero_image_size": {"cover", "contain", "auto", "100% 100%"},
        "page_image_size": {"cover", "contain", "auto", "100% 100%"},
        "hero_image_repeat": {"no-repeat", "repeat", "repeat-x", "repeat-y"},
        "page_image_repeat": {"no-repeat", "repeat", "repeat-x", "repeat-y"},
        "page_image_attachment": {"scroll", "fixed"},
    }
    enum_fallbacks = {"hero_image_size": "cover", "page_image_size": "cover", "hero_image_repeat": "no-repeat", "page_image_repeat": "no-repeat", "page_image_attachment": "fixed"}
    for key, allowed in enum_settings.items():
        if defaults.get(key) not in allowed:
            defaults[key] = enum_fallbacks[key]
    defaults["hero_shape_enabled"] = str(defaults.get("hero_shape_enabled", "false")).strip().lower() in {"1", "true", "yes", "on", "oui"}
    defaults["hero_overlay_rgba"] = css_rgba(defaults["hero_overlay_color"], defaults["hero_overlay_opacity"])
    defaults["page_overlay_rgba"] = css_rgba(defaults["page_overlay_color"], defaults["page_overlay_opacity"])
    if defaults.get("font_family") not in {"DM Sans", "Manrope", "Arial", "Inter", "system-ui"}:
        defaults["font_family"] = "DM Sans"
    return defaults


def configured_links(settings_values: dict, key: str, defaults: list[dict]) -> list[dict]:
    try:
        rows = json.loads(settings_values.get(key, "[]"))
        if not isinstance(rows, list):
            return defaults
        output = []
        for item in rows[:12]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()[:80]
            url = str(item.get("url", "")).strip()[:500]
            icon = str(item.get("icon", "•")).strip()[:8]
            if label and (url.startswith("/") and not url.startswith("//") or url.startswith("https://")):
                output.append({"label": label, "url": url, "icon": icon or "•"})
        return output
    except (ValueError, TypeError):
        return defaults


def links_to_text(raw: str, with_icon: bool = False) -> list[dict]:
    rows = []
    for line in (raw or "").splitlines()[:12]:
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        label, url = parts[0][:80], parts[1][:500]
        icon = parts[2][:8] if with_icon and len(parts) > 2 else "•"
        if label and (url.startswith("/") and not url.startswith("//") or url.startswith("https://")):
            rows.append({"label": label, "url": url, "icon": icon})
    return rows


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def check_csrf(request: Request, token: str):
    expected = request.session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, token or ""):
        raise HTTPException(status_code=403, detail="Jeton CSRF invalide. Rechargez la page.")


def render(request: Request, template: str, db: Session | None = None, status_code: int = 200, **context):
    own_db = db is None
    db = db or SessionLocal()
    try:
        values = {
            "request": request,
            "user": get_user(request),
            "is_admin": is_admin(get_user(request)),
            "settings": settings_dict(db),
            "nav_items": configured_links(settings_dict(db), "nav_items", []),
            "quick_links": configured_links(settings_dict(db), "quick_links", []),
            "footer_pages": db.query(CmsPage).filter(CmsPage.status == "published", CmsPage.show_in_footer.is_(True)).order_by(CmsPage.title).all(),
            "csrf_token": csrf_token(request),
            "oidc_configured": oidc_configured(),
            "local_auth_enabled": local_auth_enabled(),
            "auth_mode": settings.auth_mode,
            "oidc_button_label": settings.oidc_button_label,
            "flash": request.session.pop("flash", None),
            "analytics_consent_pending": settings.analytics_enabled and settings.analytics_require_consent and request.headers.get("dnt") != "1" and request.cookies.get("faq_analytics_consent") not in {"accepted", "refused"},
            "analytics_consent": request.cookies.get("faq_analytics_consent", "unknown"),
        }
        values.update(context)
        return templates.TemplateResponse(request=request, name=template, context=values, status_code=status_code)
    finally:
        if own_db:
            db.close()


def require_admin(request: Request):
    user = get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentification requise.")
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs.")
    return user


def require_user(request: Request):
    user = get_user(request)
    if not user:
        return None
    return user


def set_flash(request: Request, message: str, kind: str = "success"):
    request.session["flash"] = {"message": message, "kind": kind}


def create_content_revision(db: Session, content_type: str, content_id: int, title: str, slug: str, summary: str, content_html: str, metadata: dict, user: dict, revision_type: str = "manual"):
    revision = ContentRevision(
        content_type=content_type, content_id=content_id, title=(title or "Sans titre")[:220],
        slug=(slug or "")[:240], summary=(summary or "")[:500], content_html=content_html or "",
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False), revision_type=revision_type,
        created_by=str(user.get("email") or user.get("sub") or "")[:255],
    )
    db.add(revision)
    db.flush()
    # Conserver les 30 versions les plus récentes par contenu.
    obsolete = db.query(ContentRevision.id).filter(
        ContentRevision.content_type == content_type, ContentRevision.content_id == content_id
    ).order_by(desc(ContentRevision.created_at), desc(ContentRevision.id)).offset(30).all()
    if obsolete:
        db.query(ContentRevision).filter(ContentRevision.id.in_([row[0] for row in obsolete])).delete(synchronize_session=False)
    return revision


def unique_content_slug(db: Session, model, slug: str, content_id: int = 0) -> str:
    base = slugify(slug)
    candidate = base
    suffix = 2
    while db.query(model).filter(model.slug == candidate, model.id != content_id).first():
        candidate = f"{base[:220]}-{suffix}"
        suffix += 1
    return candidate


def analytics_secret() -> bytes:
    return (settings.analytics_salt or settings.secret_key).encode("utf-8")


def visitor_identity(request: Request) -> tuple[str, str]:
    token = request.cookies.get("faq_visitor", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", token):
        token = secrets.token_urlsafe(32)
    digest = hmac.new(analytics_secret(), token.encode("utf-8"), hashlib.sha256).hexdigest()
    return token, digest


def user_identity_hash(user: dict) -> str:
    subject = str(user.get("sub", ""))
    return hmac.new(analytics_secret(), subject.encode("utf-8"), hashlib.sha256).hexdigest()


def service_for_user(user: dict | None) -> str:
    if not user:
        return "Public / non connecté"
    value = user.get("service") or user.get("department") or user.get("department_name") or user.get("ou")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("displayName") or ""
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    return label[:120] or "Non renseigné"


def safe_search_term(value: str) -> str:
    term = re.sub(r"\s+", " ", (value or "")).strip().lower()
    term = re.sub(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", "[email]", term, flags=re.I)
    term = re.sub(r"(?<!\w)(?:\+?\d[\d .()/-]{6,}\d)(?!\w)", "[numéro]", term)
    return term[:180]


def record_analytics(
    request: Request,
    db: Session,
    event_type: str,
    *,
    article: Article | None = None,
    search_term: str = "",
    category: str = "",
    result_count: int | None = None,
) -> str | None:
    """Enregistre un événement minimal et pseudonymisé, sans IP ni user-agent."""
    if not settings.analytics_enabled or request.headers.get("dnt") == "1":
        return None
    if settings.analytics_require_consent and request.cookies.get("faq_analytics_consent") != "accepted":
        return None
    visitor_token, visitor_hash = visitor_identity(request)
    user = get_user(request)
    db.add(AnalyticsEvent(
        event_type=event_type,
        article_id=article.id if article else None,
        search_term=safe_search_term(search_term),
        category=(category or (article.category if article else ""))[:120],
        service=service_for_user(user),
        visitor_hash=visitor_hash,
        result_count=result_count,
    ))
    db.commit()
    return visitor_token


def set_visitor_cookie(response, request: Request, token: str | None):
    if token and request.cookies.get("faq_visitor") != token:
        response.set_cookie(
            "faq_visitor", token, max_age=60 * 60 * 24 * 180,
            httponly=True, secure=settings.environment == "production",
            samesite="lax", path="/",
        )
    return response


def extract_cover_image(content_html: str) -> str:
    match = re.search(r"<img\b[^>]*?\bsrc=[\"']([^\"']+)[\"']", content_html or "", re.I)
    return match.group(1) if match else ""


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    # Ajout non destructif de la colonne de couverture pour les installations existantes.
    from sqlalchemy import inspect, text
    if "cover_image" not in {column["name"] for column in inspect(engine).get_columns("articles")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE articles ADD COLUMN cover_image VARCHAR(500) NOT NULL DEFAULT ''"))
    with SessionLocal() as db:
        defaults = {
            "brand_name": settings.app_name,
            "brand_tagline": "Les réponses utiles, simplement.",
            "brand_color": "#3157a4",
            "brand_logo_url": "",
            "footer_text": "Centre d'aide — Base de connaissances",
            "header_subtitle": "ESPACE RESSOURCES",
            "home_welcome": "Bonjour et bienvenue sur",
            "home_section_title": "Fiches pratiques et tutoriels",
        }
        for key, value in defaults.items():
            if not db.get(AppSetting, key):
                db.add(AppSetting(key=key, value=value))
        analytics_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.analytics_retention_days)
        db.query(AnalyticsEvent).filter(AnalyticsEvent.created_at < analytics_cutoff).delete(synchronize_session=False)
        if settings.local_auth_enabled and db.query(LocalAccount).count() == 0:
            username = settings.local_admin_username
            password = settings.local_admin_password
            if not username or not password:
                raise RuntimeError(
                    "AUTH_MODE inclut local, mais aucun administrateur local n'existe. "
                    "Définissez LOCAL_ADMIN_USERNAME et LOCAL_ADMIN_PASSWORD pour le premier démarrage."
                )
            if len(password) < 14:
                raise RuntimeError("LOCAL_ADMIN_PASSWORD doit contenir au moins 14 caractères.")
            db.add(LocalAccount(username=username, password_hash=hash_password(password), is_admin=True, enabled=True))
        if os.getenv("SEED_DEMO", "false").lower() in {"1", "true", "yes", "oui"} and db.query(Article).count() == 0:
            demo_articles = [
                Article(
                    title="Exemple — Se connecter au Wi-Fi professionnel",
                    slug="exemple-wifi-professionnel",
                    summary="Un exemple de fiche pas-à-pas pour présenter une procédure informatique.",
                    category="Informatique", tags="wifi, réseau, connexion", status="published", featured=True,
                    content_html="<h2>Avant de commencer</h2><p>Cette fiche est un exemple à remplacer par votre procédure interne validée.</p><ol><li>Ouvrez les paramètres réseau de votre appareil.</li><li>Sélectionnez le réseau Wi-Fi professionnel correspondant à votre site.</li><li>Suivez la méthode d'authentification communiquée par votre équipe informatique.</li></ol><blockquote>Ne publiez jamais de mot de passe ni de clé Wi-Fi dans une fiche publique.</blockquote>",
                    created_by="demo", updated_by="demo",
                ),
                Article(
                    title="Exemple — Accéder à un dossier partagé",
                    slug="exemple-dossier-partage",
                    summary="Modèle de tutoriel expliquant comment retrouver un espace documentaire partagé.",
                    category="Informatique", tags="fichier, partage, windows", status="published",
                    content_html="<h2>Procédure</h2><p>Remplacez ce texte par le chemin réseau et les règles d'accès propres à votre organisation.</p><ol><li>Ouvrez l'explorateur de fichiers.</li><li>Saisissez le chemin du partage validé par votre support.</li><li>En cas de refus d'accès, transmettez le nom du dossier et le message affiché au support.</li></ol>",
                    created_by="demo", updated_by="demo",
                ),
                Article(
                    title="Exemple — Publier une procédure métier",
                    slug="exemple-procedure-metier",
                    summary="Structure type d'une fiche métier : objectif, prérequis, étapes et points de vigilance.",
                    category="Métiers", tags="procédure, métier, guide", status="published",
                    content_html="<h2>Objectif</h2><p>Décrivez le résultat attendu et les profils concernés.</p><h2>Prérequis</h2><ul><li>Indiquer les accès nécessaires.</li><li>Préciser les documents à préparer.</li></ul><h2>Étapes</h2><p>Décomposez l'opération en actions courtes et illustrées.</p><h2>En cas de difficulté</h2><p>Indiquez l'équipe à contacter et les informations utiles à fournir.</p>",
                    created_by="demo", updated_by="demo",
                ),
            ]
            db.add_all(demo_articles)
        db.commit()


@app.get("/analytics/preferences", response_class=HTMLResponse)
def analytics_preferences(request: Request, db: Session = Depends(get_db)):
    return render(request, "analytics_preferences.html", db=db)


@app.post("/analytics/consent")
def analytics_consent(request: Request, csrf: str = Form(...), decision: str = Form(...)):
    check_csrf(request, csrf)
    if decision not in {"accepted", "refused"}:
        raise HTTPException(status_code=422, detail="Choix de consentement invalide.")
    referer = request.headers.get("referer", "/")
    parsed = urlparse(referer)
    destination = parsed.path or "/"
    if parsed.query:
        destination += "?" + parsed.query
    if not destination.startswith("/") or destination.startswith("//"):
        destination = "/"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        "faq_analytics_consent", decision, max_age=60 * 60 * 24 * 180,
        httponly=True, secure=settings.environment == "production", samesite="lax", path="/",
    )
    if decision == "refused":
        response.delete_cookie("faq_visitor", path="/")
    return response


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(func.now().select())
    return {"status": "ok", "database": "connected"}


@app.get("/api/integrations/glpi/v1/search")
def glpi_search_api(request: Request, db: Session = Depends(get_db)):
    """API de recherche en lecture seule pour le plugin GLPI faqportal.

    Aucun contenu privé, brouillon, historique ou question n'est exposé.
    La clé est transmise uniquement dans l'en-tête Authorization côté serveur.
    """
    configured_token = settings.glpi_api_token
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied_token = authorization.partition(" ")
    if not configured_token:
        raise HTTPException(status_code=503, detail="Intégration GLPI non configurée")
    if scheme.lower() != "bearer" or not supplied_token or not secrets.compare_digest(
        supplied_token.encode("utf-8"), configured_token.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Authentification API invalide")

    raw_query = request.query_params.get("q", "")
    term = re.sub(r"\s+", " ", raw_query).strip()
    if len(term) < 2:
        return JSONResponse({"results": [], "total": 0, "query": term}, headers={"Cache-Control": "no-store"})
    if len(term) > 120:
        raise HTTPException(status_code=400, detail="La recherche ne doit pas dépasser 120 caractères")

    # Les caractères de motif SQL fournis par l'utilisateur sont traités littéralement.
    escaped_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped_term}%"
    query = db.query(Article).filter(
        Article.status == "published",
        or_(
            Article.title.ilike(pattern, escape="\\"),
            Article.summary.ilike(pattern, escape="\\"),
            Article.category.ilike(pattern, escape="\\"),
            Article.tags.ilike(pattern, escape="\\"),
            Article.content_html.ilike(pattern, escape="\\"),
        ),
    ).order_by(desc(Article.featured), desc(Article.updated_at))
    total = query.count()
    try:
        requested_limit = int(request.query_params.get("limit", settings.glpi_api_max_results))
    except (TypeError, ValueError):
        requested_limit = settings.glpi_api_max_results
    result_limit = max(1, min(settings.glpi_api_max_results, requested_limit, 12))
    articles = query.limit(result_limit).all()

    base = settings.app_url.rstrip("/") + "/"
    base_host = (urlparse(settings.app_url).hostname or "").lower()
    results = []
    for article in articles:
        plain_summary = bleach.clean(article.summary or article.content_html or "", tags=[], strip=True)
        plain_summary = unescape(re.sub(r"\s+", " ", plain_summary)).strip()[:300]
        image_url = ""
        raw_image = (article.cover_image or extract_cover_image(article.content_html)).strip()
        if raw_image:
            parsed_image = urlparse(raw_image)
            if parsed_image.scheme in {"http", "https"}:
                # Ne pas transformer l'API en relais d'images externes arbitraires.
                if (parsed_image.hostname or "").lower() == base_host:
                    image_url = raw_image
            else:
                image_url = urljoin(base, raw_image.lstrip("/"))
        results.append({
            "title": article.title,
            "summary": plain_summary,
            "category": article.category or "Général",
            "url": f"{settings.app_url}/faq/{quote(article.slug, safe='')}",
            "image": image_url,
        })

    return JSONResponse(
        {"results": results, "total": total, "query": term},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", category: str = "", db: Session = Depends(get_db)):
    query = db.query(Article).filter(Article.status == "published")
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(Article.title.ilike(term), Article.summary.ilike(term), Article.content_html.ilike(term), Article.tags.ilike(term)))
    if category:
        query = query.filter(Article.category == category)
    articles = query.order_by(desc(Article.featured), desc(Article.updated_at)).limit(60).all()
    categories = [row[0] for row in db.query(Article.category).filter(Article.status == "published").distinct().order_by(Article.category).all()]
    popular = db.query(Article).filter(Article.status == "published").order_by(desc(Article.views)).limit(4).all()
    featured_article = db.query(Article).filter(Article.status == "published", Article.featured.is_(True)).order_by(desc(Article.updated_at)).first()
    if not featured_article:
        featured_article = db.query(Article).filter(Article.status == "published").order_by(desc(Article.updated_at)).first()
    article_cards = [{"article": item, "cover": item.cover_image or extract_cover_image(item.content_html)} for item in articles]
    visitor_token = None
    if q.strip():
        visitor_token = record_analytics(request, db, "search", search_term=q, category=category, result_count=len(articles))
    response = render(
        request, "index.html", db=db, articles=articles, article_cards=article_cards,
        categories=categories, popular=popular, featured_article=featured_article,
        featured_cover=(featured_article.cover_image or extract_cover_image(featured_article.content_html)) if featured_article else "",
        q=q, selected_category=category,
    )
    return set_visitor_cookie(response, request, visitor_token)


@app.get("/faq/{slug}", response_class=HTMLResponse)
def article_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.slug == slug, Article.status == "published").first()
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    visitor_token = record_analytics(request, db, "faq_view", article=article)
    if visitor_token:
        article.views += 1
        db.commit()
    user = get_user(request)
    is_following = False
    follower_count = db.query(ArticleFollow).filter(ArticleFollow.article_id == article.id).count()
    if user:
        user_hash = user_identity_hash(user)
        is_following = db.query(ArticleFollow).filter(ArticleFollow.article_id == article.id, ArticleFollow.user_hash == user_hash).first() is not None
    related = db.query(Article).filter(Article.status == "published", Article.category == article.category, Article.id != article.id).order_by(desc(Article.updated_at)).limit(3).all()
    response = render(request, "article.html", db=db, article=article, related=related, is_following=is_following, follower_count=follower_count)
    return set_visitor_cookie(response, request, visitor_token)


@app.post("/faq/{slug}/suivre")
def toggle_article_follow(slug: str, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse(f"/auth/login?next=/faq/{quote(slug, safe='')}", status_code=303)
    check_csrf(request, csrf)
    article = db.query(Article).filter(Article.slug == slug, Article.status == "published").first()
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    user_hash = user_identity_hash(user)
    existing = db.query(ArticleFollow).filter(ArticleFollow.article_id == article.id, ArticleFollow.user_hash == user_hash).first()
    if existing:
        db.delete(existing)
        message = "Vous ne suivez plus cette fiche."
    else:
        db.add(ArticleFollow(article_id=article.id, user_hash=user_hash, service=service_for_user(user)))
        message = "Cette fiche a été ajoutée à vos suivis."
    db.commit()
    set_flash(request, message)
    return RedirectResponse(f"/faq/{quote(slug, safe='')}", status_code=303)


@app.get("/mes-fiches-suivies", response_class=HTMLResponse)
def my_followed_articles(request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/auth/login?next=/mes-fiches-suivies", status_code=303)
    user_hash = user_identity_hash(user)
    articles = db.query(Article).join(ArticleFollow, ArticleFollow.article_id == Article.id).filter(
        ArticleFollow.user_hash == user_hash, Article.status == "published"
    ).order_by(desc(ArticleFollow.created_at)).all()
    return render(request, "my_follows.html", db=db, articles=articles)


@app.get("/auth/login")
async def login(request: Request, next: str = "/"):
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    if get_user(request):
        return RedirectResponse(safe_next, status_code=303)
    if settings.auth_mode == "local":
        return RedirectResponse(f"/auth/local/login?next={quote(safe_next, safe='/')}", status_code=303)
    if not oidc_configured():
        if local_auth_enabled():
            return RedirectResponse(f"/auth/local/login?next={quote(safe_next, safe='/')}", status_code=303)
        raise HTTPException(status_code=503, detail="OIDC non configuré. Renseignez OIDC_DISCOVERY_URL, OIDC_CLIENT_ID et OIDC_CLIENT_SECRET.")
    request.session["next_url"] = safe_next
    redirect_uri = f"{settings.app_url}/auth/callback"
    return await oauth.oidc.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    if not oidc_configured():
        raise HTTPException(status_code=404, detail="Authentification OIDC désactivée.")
    try:
        token = await oauth.oidc.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if not userinfo:
            userinfo = await oauth.oidc.userinfo(token=token)
        user = dict(userinfo)
        destination = request.session.pop("next_url", "/")
        request.session.clear()
        request.session["user"] = {
            "sub": str(user.get("sub", "")),
            "name": str(user.get("name") or user.get("preferred_username") or user.get("email") or "Utilisateur"),
            "email": str(user.get("email", "")),
            "preferred_username": str(user.get("preferred_username", "")),
            "groups": user.get("groups", []),
            "roles": user.get("roles", []),
            "memberOf": user.get("memberOf", []),
            "service": user.get(settings.analytics_service_claim) or user.get("department") or user.get("department_name") or "",
            "realm_access": user.get("realm_access", {}),
            "resource_access": user.get("resource_access", {}),
            "auth_type": "oidc",
        }
        return RedirectResponse(destination if destination.startswith("/") and not destination.startswith("//") else "/", status_code=303)
    except (OAuthError, Exception) as exc:
        request.session["flash"] = {"message": f"Échec de l'authentification OIDC : {str(exc)[:180]}", "kind": "error"}
        return RedirectResponse("/", status_code=303)


@app.get("/auth/local/login", response_class=HTMLResponse)
def local_login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    if not local_auth_enabled():
        raise HTTPException(status_code=404, detail="Authentification locale désactivée.")
    if get_user(request):
        safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
        return RedirectResponse(safe_next, status_code=303)
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    return render(request, "local_login.html", db=db, next_url=safe_next)


@app.post("/auth/local/login", response_class=HTMLResponse)
def local_login(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(...), next: str = Form("/"), db: Session = Depends(get_db)):
    if not local_auth_enabled():
        raise HTTPException(status_code=404, detail="Authentification locale désactivée.")
    check_csrf(request, csrf)
    normalized_username = username.strip().lower()[:120]
    account = db.query(LocalAccount).filter(func.lower(LocalAccount.username) == normalized_username).first()
    now = datetime.now(timezone.utc)
    generic_error = "Identifiant ou mot de passe incorrect, ou compte temporairement verrouillé."
    if not account or not account.enabled:
        return render(request, "local_login.html", db=db, next_url=next, error=generic_error, username=username)
    if account.locked_until and account.locked_until > now:
        return render(request, "local_login.html", db=db, next_url=next, error=generic_error, username=username)
    if not verify_password(password, account.password_hash):
        account.failed_login_attempts += 1
        if account.failed_login_attempts >= 5:
            account.failed_login_attempts = 0
            account.locked_until = now + timedelta(minutes=15)
        db.commit()
        return render(request, "local_login.html", db=db, next_url=next, error=generic_error, username=username)
    account.failed_login_attempts = 0
    account.locked_until = None
    db.commit()
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    request.session.clear()
    request.session["user"] = {
        "sub": f"local:{account.id}",
        "name": account.username,
        "email": "",
        "preferred_username": account.username,
        "auth_type": "local",
        "local_account_id": account.id,
        "is_local_admin": account.is_admin,
    }
    return RedirectResponse(safe_next, status_code=303)


@app.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/questions/nouvelle", response_class=HTMLResponse)
def question_new(request: Request, db: Session = Depends(get_db)):
    if not get_user(request):
        return RedirectResponse("/auth/login?next=/questions/nouvelle", status_code=303)
    return render(request, "question_new.html", db=db)


@app.post("/questions/nouvelle")
def question_create(request: Request, title: str = Form(...), body: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = get_user(request)
    if not user:
        return RedirectResponse("/auth/login?next=/questions/nouvelle", status_code=303)
    title, body = title.strip(), body.strip()
    if len(title) < 5 or len(body) < 10:
        return render(request, "question_new.html", db=db, error="Le titre doit contenir au moins 5 caractères et la description au moins 10 caractères.", title=title, body=body, status_code=422)
    question = Question(title=title[:220], body=body, author_sub=user.get("sub", ""), author_name=user.get("name", ""), author_email=user.get("email", ""))
    db.add(question)
    db.commit()
    record_analytics(request, db, "question_submit")
    set_flash(request, "Votre question a été transmise au support.")
    return RedirectResponse("/mes-questions", status_code=303)


@app.get("/mes-questions", response_class=HTMLResponse)
def my_questions(request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/auth/login?next=/mes-questions", status_code=303)
    questions = db.query(Question).filter(Question.author_sub == user.get("sub", "")).order_by(desc(Question.created_at)).all()
    return render(request, "my_questions.html", db=db, questions=questions)


@app.get("/contenu/{slug}", response_class=HTMLResponse)
def cms_page_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    page = db.query(CmsPage).filter(CmsPage.slug == slug, CmsPage.status == "published").first()
    if not page:
        raise HTTPException(status_code=404, detail="Page introuvable")
    return render(request, "cms_page.html", db=db, page=page)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    stats = {
        "articles": db.query(Article).count(),
        "published": db.query(Article).filter(Article.status == "published").count(),
        "questions_open": db.query(Question).filter(Question.status.in_(["new", "in_progress"])).count(),
        "views": db.query(func.coalesce(func.sum(Article.views), 0)).scalar() or 0,
    }
    recent_questions = db.query(Question).order_by(desc(Question.created_at)).limit(6).all()
    return render(request, "admin/dashboard.html", db=db, stats=stats, recent_questions=recent_questions)


@app.get("/admin/analytics", response_class=HTMLResponse)
def admin_analytics(request: Request, period: int = 30, db: Session = Depends(get_db)):
    require_admin(request)
    days = period if period in {7, 30, 90, 365} else 30
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scoped = db.query(AnalyticsEvent).filter(AnalyticsEvent.created_at >= since)
    views_q = scoped.filter(AnalyticsEvent.event_type == "faq_view")
    search_q = scoped.filter(AnalyticsEvent.event_type == "search")
    total_views = views_q.count()
    unique_visitors = views_q.with_entities(func.count(func.distinct(AnalyticsEvent.visitor_hash))).scalar() or 0
    total_searches = search_q.count()
    searches_without_result = search_q.filter(AnalyticsEvent.result_count == 0).count()
    questions_created = db.query(Question).filter(Question.created_at >= since).count()
    open_questions = db.query(Question).filter(Question.status.in_(["new", "in_progress"])).count()
    active_follows = db.query(ArticleFollow).count()

    top_pages = db.query(
        Article.id, Article.title, Article.category,
        func.count(AnalyticsEvent.id).label("views"),
        func.count(func.distinct(AnalyticsEvent.visitor_hash)).label("visitors"),
    ).join(AnalyticsEvent, AnalyticsEvent.article_id == Article.id).filter(
        AnalyticsEvent.event_type == "faq_view", AnalyticsEvent.created_at >= since
    ).group_by(Article.id, Article.title, Article.category).order_by(desc("views")).limit(12).all()

    top_searches = db.query(
        AnalyticsEvent.search_term,
        func.count(AnalyticsEvent.id).label("count"),
        func.sum(case((AnalyticsEvent.result_count == 0, 1), else_=0)).label("without_result"),
    ).filter(
        AnalyticsEvent.event_type == "search", AnalyticsEvent.created_at >= since,
        AnalyticsEvent.search_term != "",
    ).group_by(AnalyticsEvent.search_term).order_by(desc("count")).limit(12).all()

    search_rows = search_q.with_entities(AnalyticsEvent.search_term).filter(AnalyticsEvent.search_term != "").all()
    stop_words = {
        "avec", "sans", "dans", "pour", "sur", "sous", "chez", "depuis", "vers", "entre", "comment", "pourquoi",
        "quelle", "quelles", "quel", "quels", "est", "sont", "etre", "avoir", "faire", "mon", "ma", "mes",
        "ton", "ta", "tes", "son", "sa", "ses", "notre", "nos", "votre", "vos", "leur", "leurs",
        "les", "des", "une", "un", "du", "de", "la", "le", "en", "et", "ou", "au", "aux", "ce", "cet", "cette",
        "qui", "que", "quoi", "dont", "pas", "plus", "moins", "peut", "peux", "comment", "bonjour",
    }
    word_counter = Counter()
    for (phrase,) in search_rows:
        words = set(re.findall(r"[a-zà-ÿ0-9]{3,}", phrase or "", flags=re.I))
        word_counter.update(word.lower() for word in words if word.lower() not in stop_words and not word.isdigit())
    top_words = [{"word": word, "count": count} for word, count in word_counter.most_common(12)]

    top_categories = db.query(
        AnalyticsEvent.category, func.count(AnalyticsEvent.id).label("views")
    ).filter(
        AnalyticsEvent.event_type == "faq_view", AnalyticsEvent.created_at >= since,
        AnalyticsEvent.category != "",
    ).group_by(AnalyticsEvent.category).order_by(desc("views")).limit(10).all()

    top_followed = db.query(
        Article.id, Article.title, Article.category,
        func.count(ArticleFollow.id).label("followers"),
    ).join(ArticleFollow, ArticleFollow.article_id == Article.id).filter(
        Article.status == "published"
    ).group_by(Article.id, Article.title, Article.category).order_by(desc("followers")).limit(12).all()

    service_views = db.query(
        AnalyticsEvent.service,
        func.count(AnalyticsEvent.id).label("views"),
        func.count(func.distinct(AnalyticsEvent.visitor_hash)).label("visitors"),
    ).filter(
        AnalyticsEvent.event_type == "faq_view", AnalyticsEvent.created_at >= since
    ).group_by(AnalyticsEvent.service).all()
    service_searches = db.query(
        AnalyticsEvent.service, func.count(AnalyticsEvent.id).label("searches")
    ).filter(
        AnalyticsEvent.event_type == "search", AnalyticsEvent.created_at >= since
    ).group_by(AnalyticsEvent.service).all()
    service_questions = db.query(
        AnalyticsEvent.service, func.count(AnalyticsEvent.id).label("questions")
    ).filter(
        AnalyticsEvent.event_type == "question_submit", AnalyticsEvent.created_at >= since
    ).group_by(AnalyticsEvent.service).all()
    service_follows = db.query(
        ArticleFollow.service, func.count(ArticleFollow.id).label("follows")
    ).group_by(ArticleFollow.service).all()
    service_map = {}
    def service_bucket(key):
        key = key or "Non renseigné"
        return service_map.setdefault(key, {"service": key, "views": 0, "visitors": 0, "searches": 0, "questions": 0, "follows": 0})
    for row in service_views:
        bucket = service_bucket(row.service)
        bucket["views"] = row.views
        bucket["visitors"] = row.visitors
    for row in service_searches:
        service_bucket(row.service)["searches"] = row.searches
    for row in service_questions:
        service_bucket(row.service)["questions"] = row.questions
    for row in service_follows:
        service_bucket(row.service)["follows"] = row.follows
    services = sorted(service_map.values(), key=lambda item: (item["views"] + item["searches"] + item["questions"]), reverse=True)[:12]

    daily_rows = db.query(
        func.date(AnalyticsEvent.created_at).label("day"), AnalyticsEvent.event_type,
        func.count(AnalyticsEvent.id).label("count"),
    ).filter(
        AnalyticsEvent.created_at >= max(since, datetime.now(timezone.utc) - timedelta(days=30)),
        AnalyticsEvent.event_type.in_(["faq_view", "search"]),
    ).group_by(func.date(AnalyticsEvent.created_at), AnalyticsEvent.event_type).order_by(func.date(AnalyticsEvent.created_at)).all()
    daily_map = {}
    for row in daily_rows:
        day_key = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
        daily_map.setdefault(day_key, {"day": day_key, "views": 0, "searches": 0})
        daily_map[day_key]["views" if row.event_type == "faq_view" else "searches"] = row.count
    daily_activity = sorted(daily_map.values(), key=lambda item: item["day"])
    max_daily = max([item["views"] + item["searches"] for item in daily_activity] or [1])
    return render(
        request, "admin/analytics.html", db=db, period=days,
        period_start_label=since.strftime("%d/%m/%Y"), period_end_label=datetime.now(timezone.utc).strftime("%d/%m/%Y"),
        analytics_stats={
            "views": total_views, "visitors": unique_visitors,
            "searches": total_searches, "without_result": searches_without_result,
            "questions": questions_created, "open_questions": open_questions,
            "follows": active_follows,
        },
        top_pages=top_pages, top_searches=top_searches, top_words=top_words, top_categories=top_categories, top_followed=top_followed,
        services=services, daily_activity=daily_activity, max_daily=max_daily,
    )


@app.get("/admin/analytics/export.csv")
def admin_analytics_export(request: Request, period: int = 30, db: Session = Depends(get_db)):
    require_admin(request)
    days = period if period in {7, 30, 90, 365} else 30
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.query(
        Article.id, Article.title, Article.category,
        func.count(AnalyticsEvent.id).label("views"),
        func.count(func.distinct(AnalyticsEvent.visitor_hash)).label("visitors"),
    ).outerjoin(AnalyticsEvent, (AnalyticsEvent.article_id == Article.id) & (AnalyticsEvent.event_type == "faq_view") & (AnalyticsEvent.created_at >= since)).filter(
        Article.status == "published"
    ).group_by(Article.id, Article.title, Article.category).order_by(desc("views")).all()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["ID", "Fiche FAQ", "Catégorie", "Consultations", "Visiteurs uniques", "Abonnés actifs"])
    for row in rows:
        followers = db.query(ArticleFollow).filter(ArticleFollow.article_id == row.id).count()
        writer.writerow([row.id, row.title, row.category, row.views, row.visitors, followers])
    content = "\ufeff" + output.getvalue()
    return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=faq-analytics-{days}j.csv"})


@app.get("/admin/articles", response_class=HTMLResponse)
def admin_articles(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    articles = db.query(Article).order_by(desc(Article.updated_at)).all()
    return render(request, "admin/articles.html", db=db, articles=articles)


@app.get("/admin/articles/nouveau", response_class=HTMLResponse)
def admin_article_new(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    return render(request, "admin/article_form.html", db=db, article=None)


@app.get("/admin/articles/{article_id}/modifier", response_class=HTMLResponse)
def admin_article_edit(article_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article introuvable")
    latest_auto = db.query(ContentRevision).filter(
        ContentRevision.content_type == "article", ContentRevision.content_id == article.id, ContentRevision.revision_type == "auto"
    ).order_by(desc(ContentRevision.created_at), desc(ContentRevision.id)).first()
    if latest_auto and article.updated_at and latest_auto.created_at and latest_auto.created_at.replace(tzinfo=timezone.utc) >= article.updated_at.replace(tzinfo=timezone.utc):
        draft_revision = latest_auto
    else:
        draft_revision = None
    return render(request, "admin/article_form.html", db=db, article=article, draft_revision=draft_revision, draft_meta=json.loads(draft_revision.metadata_json or "{}") if draft_revision else {})


@app.post("/admin/articles/enregistrer")
def admin_article_save(request: Request, csrf: str = Form(...), article_id: int = Form(0), title: str = Form(...), slug: str = Form(""), summary: str = Form(""), content_html: str = Form(""), category: str = Form("Général"), tags: str = Form(""), status: str = Form("draft"), featured: str | None = Form(None), cover_image: str = Form(""), pdf_file: UploadFile | None = File(None), db: Session = Depends(get_db)):
    user = require_admin(request)
    check_csrf(request, csrf)
    title = title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Le titre est obligatoire")
    slug = slugify(slug or title)
    existing_slug = db.query(Article).filter(Article.slug == slug, Article.id != article_id).first()
    if existing_slug:
        slug = f"{slug}-{uuid.uuid4().hex[:5]}"
    article = db.get(Article, article_id) if article_id else Article(created_by=user.get("email", user.get("sub", "")))
    if article is None:
        raise HTTPException(status_code=404, detail="Article introuvable")
    if article_id:
        create_content_revision(db, "article", article.id, article.title, article.slug, article.summary, article.content_html,
                                {"category": article.category, "tags": article.tags, "featured": article.featured, "cover_image": article.cover_image, "status": article.status}, user, "manual")
    article.title = title[:220]
    article.slug = slug
    article.summary = summary.strip()[:500]
    article.content_html = clean_html(content_html)
    article.category = category.strip()[:120] or "Général"
    article.tags = tags.strip()[:500]
    article.status = status if status in {"draft", "published"} else "draft"
    article.featured = featured == "on"
    article.cover_image = cover_image.strip()[:500]
    article.updated_by = user.get("email", user.get("sub", ""))
    db.add(article)
    db.flush()

    if pdf_file and pdf_file.filename:
        pdf_name = Path(pdf_file.filename.replace("\\\\", "/")).name
        pdf_raw = pdf_file.file.read()
        if Path(pdf_name).suffix.lower() != ".pdf" or not pdf_raw.startswith(b"%PDF-"):
            db.rollback()
            raise HTTPException(status_code=415, detail="Le document joint doit être un fichier PDF valide.")
        if len(pdf_raw) > 30 * 1024 * 1024:
            db.rollback()
            raise HTTPException(status_code=413, detail="Le PDF dépasse la limite de 30 Mo.")
        for previous in db.query(DocumentAsset).filter(DocumentAsset.article_id == article.id).all():
            (DOCUMENT_DIR / previous.file_name).unlink(missing_ok=True)
            db.delete(previous)
        document_id = uuid.uuid4().hex
        stored_name = f"{document_id}.pdf"
        stored_path = DOCUMENT_DIR / stored_name
        stored_path.write_bytes(pdf_raw)
        db.add(DocumentAsset(id=document_id, article_id=article.id, original_name=pdf_name[:255],
                             file_name=stored_name, size_bytes=len(pdf_raw)))
        article.content_html = re.sub(r'<iframe[^>]*class="embedded-pdf-viewer"[^>]*></iframe>', '', article.content_html or "")
        article.content_html += (
            f'<h2>Document associé</h2><iframe class="embedded-pdf-viewer" '
            f'src="/documents/{document_id}/viewer" title="{escape(pdf_name, quote=True)}" '
            f'width="100%" height="900"></iframe>'
        )
    db.commit()
    set_flash(request, "Article enregistré." + (" PDF joint et visionneuse intégrée." if pdf_file and pdf_file.filename else ""))
    return RedirectResponse("/admin/articles", status_code=303)


@app.post("/admin/articles/{article_id}/supprimer")
def admin_article_delete(article_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request)
    check_csrf(request, csrf)
    article = db.get(Article, article_id)
    if article:
        for asset in db.query(DocumentAsset).filter(DocumentAsset.article_id == article.id).all():
            (DOCUMENT_DIR / asset.file_name).unlink(missing_ok=True)
            db.delete(asset)
        db.delete(article)
        db.commit()
    set_flash(request, "Article supprimé.")
    return RedirectResponse("/admin/articles", status_code=303)


@app.get("/admin/questions", response_class=HTMLResponse)
def admin_questions(request: Request, status: str = "", db: Session = Depends(get_db)):
    require_admin(request)
    query = db.query(Question)
    if status in {"new", "in_progress", "answered", "closed"}:
        query = query.filter(Question.status == status)
    questions = query.order_by(desc(Question.created_at)).all()
    return render(request, "admin/questions.html", db=db, questions=questions, selected_status=status)


@app.post("/admin/questions/{question_id}/traiter")
def admin_question_update(question_id: int, request: Request, csrf: str = Form(...), status: str = Form("new"), answer: str = Form(""), db: Session = Depends(get_db)):
    user = require_admin(request)
    check_csrf(request, csrf)
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question introuvable")
    question.status = status if status in {"new", "in_progress", "answered", "closed"} else "new"
    question.answer = answer.strip()
    question.answered_by = user.get("email", user.get("sub", "")) if answer.strip() else ""
    db.commit()
    set_flash(request, "Question mise à jour.")
    return RedirectResponse("/admin/questions", status_code=303)


@app.get("/admin/security", response_class=HTMLResponse)
def admin_security(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request)
    local_account = None
    if user.get("auth_type") == "local" and user.get("local_account_id"):
        local_account = db.get(LocalAccount, user["local_account_id"])
    return render(request, "admin/security.html", db=db, local_account=local_account)


@app.post("/admin/security/password")
def admin_security_password(
    request: Request,
    csrf: str = Form(...),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_admin(request)
    check_csrf(request, csrf)
    if user.get("auth_type") != "local" or not user.get("local_account_id"):
        raise HTTPException(status_code=403, detail="La modification du mot de passe local nécessite une session administrateur locale.")
    account = db.get(LocalAccount, user["local_account_id"])
    if not account or not verify_password(current_password, account.password_hash):
        return render(request, "admin/security.html", db=db, local_account=account, error="Le mot de passe actuel est incorrect.", status_code=422)
    if len(new_password) < 14:
        return render(request, "admin/security.html", db=db, local_account=account, error="Le nouveau mot de passe doit contenir au moins 14 caractères.", status_code=422)
    if new_password != confirm_password:
        return render(request, "admin/security.html", db=db, local_account=account, error="La confirmation du nouveau mot de passe ne correspond pas.", status_code=422)
    account.password_hash = hash_password(new_password)
    account.failed_login_attempts = 0
    account.locked_until = None
    db.commit()
    set_flash(request, "Mot de passe local modifié.")
    return RedirectResponse("/admin/security", status_code=303)


@app.get("/admin/branding", response_class=HTMLResponse)
def admin_branding(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    return RedirectResponse("/admin/portal", status_code=302)


@app.get("/admin/portal", response_class=HTMLResponse)
def admin_portal_editor(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    current = settings_dict(db)
    defaults = settings_dict_empty_defaults()
    nav = configured_links(current, "nav_items", [])
    quick = configured_links(current, "quick_links", [])
    nav_text = "\n".join(f"{x['label']} | {x['url']}" for x in nav)
    quick_text = "\n".join(f"{x['label']} | {x['url']} | {x.get('icon','•')}" for x in quick)
    return render(request, "admin/portal_editor.html", db=db, nav_text=nav_text, quick_links_text=quick_text, settings_defaults=defaults)


def settings_dict_empty_defaults() -> dict:
    # Valeurs de référence pour permettre au formulaire de restaurer chaque groupe.
    return {
        "brand_name": settings.app_name, "brand_tagline": "Les réponses utiles, simplement.",
        "brand_color": "#477cbd", "brand_logo_url": "", "header_subtitle": "ESPACE RESSOURCES",
        "footer_text": "Centre d'aide — Base de connaissances", "footer_secondary_text": "Une base de connaissances évolutive",
        "footer_secondary_url": "/analytics/preferences", "search_placeholder": "Rechercher un article, une procédure, une réponse…",
        "search_button_label": "Rechercher", "oidc_button_label": settings.oidc_button_label, "local_button_label": "Compte local",
        "logout_button_label": "Déconnexion", "my_follows_nav_label": "Mes fiches", "my_questions_nav_label": "Mes questions",
        "home_welcome": "Bonjour et bienvenue sur", "home_featured_label": "À LA UNE",
        "home_featured_cta": "Consulter la fiche", "home_empty_title": "Les bonnes réponses, au bon endroit.",
        "home_empty_text": "Des guides courts et des procédures pour gagner du temps au quotidien.",
        "home_quick_access_title": "Accès rapides", "home_section_eyebrow": "BASE DE CONNAISSANCES",
        "home_section_title": "Fiches pratiques et tutoriels", "home_popular_title": "Les fiches les plus consultées",
        "home_question_eyebrow": "VOUS NE TROUVEZ PAS LA RÉPONSE ?",
        "home_question_title": "Une question reste sans réponse ?",
        "home_question_body": "Transmettez votre demande à l'équipe métier ou au support informatique. La connexion entreprise est requise.",
        "home_question_button": "Poser une question", "home_custom_html": "",
        "article_follow_title": "Garder cette fiche sous la main", "article_follow_body": "Suivez-la pour la retrouver depuis votre espace personnel.",
        "article_follow_button": "Suivre cette fiche", "article_unfollow_button": "Ne plus suivre",
        "article_help_title": "Vous n'avez pas trouvé la réponse ?", "article_help_body": "Adressez une question au support ou à l'équipe métier.",
        "article_help_button": "Poser une question", "article_related_title": "Dans la même catégorie", "article_suggestion_button": "Faire une suggestion",
        "question_page_kicker": "CONTACT SUPPORT / MÉTIER", "question_page_title": "Poser une question",
        "question_page_body": "Décrivez votre besoin avec suffisamment de détails pour permettre à l'équipe concernée de vous répondre efficacement.",
        "question_title_label": "Objet de la question", "question_body_label": "Description",
        "question_submit_button": "Envoyer la question", "question_cancel_button": "Annuler",
        "question_privacy_note": "Ne transmettez pas de mot de passe ni de donnée personnelle sensible.",
        "user_area_eyebrow": "ESPACE UTILISATEUR", "my_questions_title": "Mes questions",
        "my_questions_intro": "Suivi des demandes transmises au support.", "my_questions_new_button": "Nouvelle question",
        "my_questions_empty_title": "Aucune question pour le moment", "my_questions_empty_text": "Vos demandes apparaîtront ici après leur envoi.",
        "my_follows_title": "Mes fiches suivies", "my_follows_intro": "Retrouvez ici les procédures que vous avez choisi de suivre.",
        "my_follows_empty_title": "Aucune fiche suivie", "my_follows_empty_text": "Ouvrez une fiche FAQ et sélectionnez « Suivre cette fiche » pour la retrouver ici.",
        "my_follows_open_button": "Explorer la FAQ", "my_follows_list_button": "Parcourir les fiches",
        "login_title": "Connexion locale", "login_intro": "Utilisez le compte administrateur local du portail FAQ.",
        "login_username_label": "Identifiant", "login_password_label": "Mot de passe", "login_submit_button": "Se connecter",
        "article_feedback_title": "Cette fiche vous a-t-elle aidé ?", "article_feedback_body": "Votre retour permettra d'améliorer les contenus.",
        "article_help_eyebrow": "BESOIN D'AIDE ?",
        "secondary_color": "#53648f", "accent_red": "#c83227", "hero_gradient_start": "#53648f",
        "hero_gradient_mid": "#68465f", "hero_gradient_end": "#a33131", "page_background": "#ffffff",
        "surface_color": "#ffffff", "text_color": "#18243a", "hero_background_image": "", "page_background_image": "",
        "hero_overlay_color": "#1e2a41", "hero_overlay_opacity": "42",
        "hero_image_size": "cover", "hero_image_position_x": "50", "hero_image_position_y": "50", "hero_image_repeat": "no-repeat",
        "hero_padding_top": "22", "hero_padding_bottom": "16", "hero_min_height": "0",
        "hero_shape_enabled": "false", "hero_shape_height": "70",
        "page_overlay_color": "#ffffff", "page_overlay_opacity": "84",
        "page_image_size": "cover", "page_image_position_x": "50", "page_image_position_y": "50",
        "page_image_repeat": "no-repeat", "page_image_attachment": "fixed",
        "font_family": "DM Sans", "font_file_url": "", "font_file_name": "",
        "content_max_width": "1290", "cards_per_row": "5", "card_radius": "11",
        "show_nav": "true", "show_search": "true", "show_hero": "true", "show_quick_links": "true", "show_categories": "true",
        "show_popular": "true", "show_question_cta": "true", "show_article_views": "true",
        "show_article_follow": "true", "show_related_articles": "true", "show_article_feedback": "true", "show_footer_secondary": "true",
    }


@app.post("/admin/portal")
async def admin_portal_save(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    form = await request.form()
    check_csrf(request, str(form.get("csrf", "")))
    defaults = settings_dict_empty_defaults()
    text_limits = {
        "brand_name": 100, "brand_tagline": 200, "brand_logo_url": 500, "header_subtitle": 100,
        "hero_background_image": 500, "page_background_image": 500, "font_file_url": 500, "font_file_name": 100,
        "search_button_label": 60, "oidc_button_label": 80, "local_button_label": 80, "logout_button_label": 80,
        "my_follows_nav_label": 80, "my_questions_nav_label": 80,
        "footer_text": 250, "footer_secondary_text": 200, "footer_secondary_url": 500, "search_placeholder": 180,
        "home_welcome": 160, "home_featured_label": 80, "home_featured_cta": 80, "home_empty_title": 220,
        "home_empty_text": 500, "home_quick_access_title": 100, "home_section_eyebrow": 100, "home_section_title": 200,
        "home_popular_title": 200, "home_question_eyebrow": 120, "home_question_title": 220, "home_question_body": 600,
        "home_question_button": 100, "article_follow_title": 160, "article_follow_body": 300, "article_follow_button": 80,
        "article_unfollow_button": 80, "article_help_title": 180, "article_help_body": 400, "article_help_button": 80,
        "article_related_title": 120, "article_suggestion_button": 100, "question_page_kicker": 120,
        "question_page_title": 180, "question_page_body": 600, "question_title_label": 100, "question_body_label": 100,
        "question_submit_button": 100, "question_cancel_button": 80, "question_privacy_note": 250,
        "user_area_eyebrow": 100, "my_questions_title": 150, "my_questions_intro": 300,
        "my_questions_new_button": 100, "my_questions_empty_title": 160, "my_questions_empty_text": 300,
        "my_follows_title": 150, "my_follows_intro": 300, "my_follows_empty_title": 160,
        "my_follows_empty_text": 300, "my_follows_open_button": 100, "my_follows_list_button": 100,
        "login_title": 120, "login_intro": 250, "login_username_label": 80, "login_password_label": 80,
        "login_submit_button": 80, "article_feedback_title": 160, "article_feedback_body": 250, "article_help_eyebrow": 100,
    }
    values = {}
    for key, limit in text_limits.items():
        value = str(form.get(key, defaults.get(key, ""))).strip()[:limit]
        if key == "brand_name" and not value:
            raise HTTPException(status_code=422, detail="Le nom du portail ne peut pas être vide.")
        values[key] = value
    url = values["brand_logo_url"]
    if url and not (url.startswith("/static/uploads/") or url.startswith("https://")):
        raise HTTPException(status_code=422, detail="Le logo doit être un fichier importé ou une URL HTTPS.")
    secondary_url = values["footer_secondary_url"]
    if secondary_url and not (secondary_url.startswith("/") and not secondary_url.startswith("//") or secondary_url.startswith("https://")):
        raise HTTPException(status_code=422, detail="Le lien secondaire du pied de page doit être local ou HTTPS.")
    for key in ("brand_color", "secondary_color", "accent_red", "hero_gradient_start", "hero_gradient_mid", "hero_gradient_end", "page_background", "surface_color", "text_color", "hero_overlay_color", "page_overlay_color"):
        color = str(form.get(key, defaults.get(key, ""))).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise HTTPException(status_code=422, detail=f"Couleur invalide pour {key} : utilisez #RRGGBB.")
        values[key] = color
    font_family = str(form.get("font_family", "DM Sans"))
    if font_family not in {"DM Sans", "Manrope", "Arial", "Inter", "system-ui", "Police importée"}:
        font_family = "DM Sans"
    values["font_family"] = font_family
    for image_key in ("hero_background_image", "page_background_image"):
        image_url = values[image_key]
        if image_url and not image_url.startswith("/static/uploads/"):
            raise HTTPException(status_code=422, detail=f"{image_key} doit provenir d’un fichier importé.")
    if values["font_file_url"] and not values["font_file_url"].startswith("/static/fonts/"):
        raise HTTPException(status_code=422, detail="La police doit provenir d’un fichier importé.")
    if values["font_file_url"]:
        values["font_family"] = "Police importée"
    numeric_limits = {
        "content_max_width": (900, 1800), "cards_per_row": (2, 6), "card_radius": (0, 28),
        "hero_overlay_opacity": (0, 100), "hero_image_position_x": (0, 100), "hero_image_position_y": (0, 100),
        "hero_padding_top": (0, 160), "hero_padding_bottom": (0, 160), "hero_min_height": (0, 900),
        "hero_shape_height": (0, 180), "page_overlay_opacity": (0, 100),
        "page_image_position_x": (0, 100), "page_image_position_y": (0, 100),
    }
    for key, (low, high) in numeric_limits.items():
        try:
            values[key] = str(max(low, min(high, int(form.get(key, defaults.get(key, low))))))
        except (TypeError, ValueError):
            values[key] = str(defaults.get(key, low))
    enum_limits = {
        "hero_image_size": {"cover", "contain", "auto", "100% 100%"},
        "page_image_size": {"cover", "contain", "auto", "100% 100%"},
        "hero_image_repeat": {"no-repeat", "repeat", "repeat-x", "repeat-y"},
        "page_image_repeat": {"no-repeat", "repeat", "repeat-x", "repeat-y"},
        "page_image_attachment": {"scroll", "fixed"},
    }
    for key, allowed in enum_limits.items():
        value = str(form.get(key, defaults.get(key, "")))
        values[key] = value if value in allowed else str(defaults.get(key, "cover"))
    for key in ("hero_shape_enabled", "show_nav", "show_search", "show_hero", "show_quick_links", "show_categories", "show_popular", "show_question_cta", "show_article_views", "show_article_follow", "show_related_articles", "show_article_feedback", "show_footer_secondary"):
        values[key] = "true" if str(form.get(key, "")).lower() in {"on", "true", "1", "yes"} else "false"
    nav_items = links_to_text(str(form.get("nav_items_text", "")))
    quick_links = links_to_text(str(form.get("quick_links_text", "")), with_icon=True)
    values["nav_items"] = json.dumps(nav_items, ensure_ascii=False)
    values["quick_links"] = json.dumps(quick_links, ensure_ascii=False)
    values["home_custom_html"] = clean_html(str(form.get("home_custom_html", ""))[:20000])
    for key, value in values.items():
        row = db.get(AppSetting, key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()
    set_flash(request, "Personnalisation complète enregistrée.")
    return RedirectResponse("/admin/portal", status_code=303)


@app.post("/admin/content/autosave")
async def admin_content_autosave(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request)
    check_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps de requête invalide.")
    content_type = str(payload.get("type", ""))
    if content_type not in {"page", "article"}:
        raise HTTPException(status_code=400, detail="Type de contenu invalide.")
    title = re.sub(r"\s+", " ", str(payload.get("title", ""))).strip()[:220]
    if not title:
        raise HTTPException(status_code=422, detail="Saisissez un titre avant la sauvegarde automatique.")
    slug_raw = str(payload.get("slug", "")).strip()[:240] or title
    summary = str(payload.get("summary", "")).strip()[:500]
    content_html = clean_html(str(payload.get("content_html", ""))[:1_500_000])
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    content_id = int(payload.get("id") or 0)
    model = CmsPage if content_type == "page" else Article
    entity = db.get(model, content_id) if content_id else None
    if content_id and not entity:
        raise HTTPException(status_code=404, detail="Contenu introuvable.")
    if not entity:
        entity = CmsPage(created_by=str(user.get("email") or user.get("sub") or "")) if content_type == "page" else Article(created_by=str(user.get("email") or user.get("sub") or ""))
        entity.status = "draft"
        db.add(entity)
    draft_slug = unique_content_slug(db, model, slug_raw, getattr(entity, "id", 0) or 0)
    if not content_id:
        # Le premier autosave crée un vrai brouillon afin de donner un identifiant stable à l'éditeur.
        entity.title = title
        entity.slug = draft_slug
        entity.summary = summary
        entity.content_html = content_html
        entity.updated_by = str(user.get("email") or user.get("sub") or "")[:255]
        if content_type == "article":
            entity.category = str(metadata.get("category") or "Général")[:120]
            entity.tags = str(metadata.get("tags") or "")[:500]
            entity.featured = bool(metadata.get("featured"))
            entity.cover_image = str(metadata.get("cover_image") or "")[:500]
        else:
            entity.show_in_footer = bool(metadata.get("show_in_footer"))
        db.add(entity)
        db.commit()
        db.refresh(entity)
        content_id = entity.id
    revision = create_content_revision(db, content_type, content_id, title, draft_slug, summary, content_html, metadata, user, "auto")
    db.commit()
    return JSONResponse({"ok": True, "id": content_id, "slug": draft_slug, "revision": revision.id, "saved_at": revision.created_at.isoformat(), "url": (f"/faq/{draft_slug}" if content_type == "article" else f"/contenu/{draft_slug}")})


@app.get("/admin/content/{content_type}/{content_id}/revisions")
def admin_content_revisions(content_type: str, content_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    if content_type not in {"page", "article"}:
        raise HTTPException(status_code=404, detail="Type de contenu inconnu.")
    rows = db.query(ContentRevision).filter(ContentRevision.content_type == content_type, ContentRevision.content_id == content_id).order_by(desc(ContentRevision.created_at), desc(ContentRevision.id)).limit(30).all()
    return JSONResponse({"items": [{"id": r.id, "title": r.title, "slug": r.slug, "summary": r.summary, "content_html": r.content_html, "metadata": json.loads(r.metadata_json or "{}"), "type": r.revision_type, "created_at": r.created_at.isoformat() if r.created_at else ""} for r in rows]})


@app.get("/admin/pages", response_class=HTMLResponse)
def admin_pages(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    pages = db.query(CmsPage).order_by(desc(CmsPage.updated_at)).all()
    return render(request, "admin/pages.html", db=db, pages=pages)


@app.get("/admin/pages/nouvelle", response_class=HTMLResponse)
def admin_page_new(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    return render(request, "admin/page_form.html", db=db, page=None)


@app.get("/admin/pages/{page_id}/modifier", response_class=HTMLResponse)
def admin_page_edit(page_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    page = db.get(CmsPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page introuvable")
    latest_auto = db.query(ContentRevision).filter(
        ContentRevision.content_type == "page", ContentRevision.content_id == page.id, ContentRevision.revision_type == "auto"
    ).order_by(desc(ContentRevision.created_at), desc(ContentRevision.id)).first()
    if latest_auto and page.updated_at and latest_auto.created_at and latest_auto.created_at.replace(tzinfo=timezone.utc) >= page.updated_at.replace(tzinfo=timezone.utc):
        draft_revision = latest_auto
    else:
        draft_revision = None
    return render(request, "admin/page_form.html", db=db, page=page, draft_revision=draft_revision, draft_meta=json.loads(draft_revision.metadata_json or "{}") if draft_revision else {})


@app.post("/admin/pages/enregistrer")
def admin_page_save(request: Request, csrf: str = Form(...), page_id: int = Form(0), title: str = Form(...), slug: str = Form(""), summary: str = Form(""), content_html: str = Form(""), status: str = Form("draft"), show_in_footer: str | None = Form(None), db: Session = Depends(get_db)):
    user = require_admin(request)
    check_csrf(request, csrf)
    title = title.strip()[:220]
    slug = slugify(slug.strip() or title)
    if not title:
        raise HTTPException(status_code=422, detail="Le titre est obligatoire.")
    duplicate = db.query(CmsPage).filter(CmsPage.slug == slug, CmsPage.id != page_id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Cette URL est déjà utilisée.")
    page = db.get(CmsPage, page_id) if page_id else CmsPage(created_by=user.get("email", user.get("sub", "")))
    if not page:
        raise HTTPException(status_code=404, detail="Page introuvable")
    if page_id:
        create_content_revision(db, "page", page.id, page.title, page.slug, page.summary, page.content_html,
                                {"show_in_footer": page.show_in_footer, "status": page.status}, user, "manual")
    page.title, page.slug = title, slug
    page.summary = summary.strip()[:500]
    page.content_html = clean_html(content_html)
    page.status = status if status in {"draft", "published"} else "draft"
    page.show_in_footer = show_in_footer == "on"
    page.updated_by = user.get("email", user.get("sub", ""))
    db.add(page)
    db.commit()
    set_flash(request, "Page enregistrée.")
    return RedirectResponse("/admin/pages", status_code=303)


@app.post("/admin/pages/{page_id}/supprimer")
def admin_page_delete(page_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_admin(request)
    check_csrf(request, csrf)
    page = db.get(CmsPage, page_id)
    if page:
        db.delete(page)
        db.commit()
    set_flash(request, "Page supprimée.")
    return RedirectResponse("/admin/pages", status_code=303)


@app.get("/documents/{document_id}/viewer", response_class=HTMLResponse)
def document_viewer(document_id: str, request: Request, db: Session = Depends(get_db)):
    if not re.fullmatch(r"[a-f0-9]{32}", document_id):
        raise HTTPException(status_code=404, detail="Document introuvable")
    asset = db.get(DocumentAsset, document_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Document introuvable")
    article = db.get(Article, asset.article_id)
    user = get_user(request)
    if not article or (article.status != "published" and not is_admin(user)):
        raise HTTPException(status_code=404, detail="Document introuvable")
    return templates.TemplateResponse(request=request, name="document_viewer.html", context={
        "document_url": f"/documents/{document_id}/file",
        "document_title": asset.original_name,
    })


@app.get("/documents/{document_id}/file")
def document_file(document_id: str, request: Request, db: Session = Depends(get_db)):
    if not re.fullmatch(r"[a-f0-9]{32}", document_id):
        raise HTTPException(status_code=404, detail="Document introuvable")
    asset = db.get(DocumentAsset, document_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Document introuvable")
    article = db.get(Article, asset.article_id)
    user = get_user(request)
    if not article or (article.status != "published" and not is_admin(user)):
        raise HTTPException(status_code=404, detail="Document introuvable")
    path = DOCUMENT_DIR / asset.file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier absent")
    # Le PDF est toujours servi en inline : aucun lien de téléchargement n'est exposé dans l'interface.
    # Cela ne constitue pas une DRM : un lecteur autorisé peut toujours récupérer les octets reçus.
    return FileResponse(
        path, media_type="application/pdf", filename=asset.original_name,
        content_disposition_type="inline",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


def _unique_import_article(db: Session, title: str, mode: str, preferred_slug: str = "") -> Article:
    """Retourne un brouillon existant à mettre à jour ou crée un slug libre.

    Une fiche déjà publiée n'est jamais écrasée par un import, même en mode upsert.
    """
    base_slug = slugify(preferred_slug or title)
    article = db.query(Article).filter(Article.slug == base_slug).first() if mode == "upsert" else None
    if article is not None and article.status == "published":
        article = None
    if article is None:
        candidate, suffix = base_slug, 2
        while db.query(Article).filter(Article.slug == candidate).first():
            candidate, suffix = f"{base_slug}-{suffix}", suffix + 1
        article = Article(title=title[:220], slug=candidate, created_by="import")
        db.add(article)
    return article


def _save_docx_image(image):
    content_type = (image.content_type or "").lower()
    extensions = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
    extension = extensions.get(content_type)
    if not extension:
        return {"src": ""}
    data = image.open().read()
    if not data or len(data) > 8 * 1024 * 1024:
        return {"src": ""}
    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(data)
    return {"src": f"/static/uploads/{filename}"}


def _parse_markdown(raw: bytes, filename: str) -> dict:
    """Convertit un fichier Markdown et lit un front matter YAML simple (clé: valeur)."""
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Le Markdown doit être encodé en UTF-8.") from exc
    metadata = {}
    if source.startswith("---"):
        lines = source.splitlines()
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() in {"---", "..."}), None)
        if closing is not None:
            for line in lines[1:closing]:
                match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
                if match:
                    value = match.group(2).strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                        value = value[1:-1]
                    metadata[match.group(1).lower().replace("-", "_")] = value
            source = "\n".join(lines[closing + 1:]).lstrip()
    title = str(metadata.get("title") or "").strip()
    if not title:
        heading = re.search(r"^#\s+(.+?)\s*#*\s*$", source, flags=re.MULTILINE)
        title = heading.group(1).strip() if heading else Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    title = title[:220] or "Article Markdown"
    # Le H1 reprend le titre de l'article : il est retiré du corps pour éviter un doublon visuel.
    source = re.sub(r"^#\s+" + re.escape(title) + r"\s*#*\s*(?:\r?\n)+", "", source, count=1, flags=re.IGNORECASE)
    import mistune
    markdown_renderer = mistune.create_markdown(escape=True, plugins=["table", "strikethrough", "task_lists", "url"])
    html_content = markdown_renderer(source)
    plain = re.sub(r"[\\`*_>#|~]", " ", source)
    plain = re.sub(r"\s+", " ", plain).strip()
    summary = str(metadata.get("summary") or plain)[:500]
    raw_tags = str(metadata.get("tags") or "")
    if raw_tags.startswith("[") and raw_tags.endswith("]"):
        raw_tags = raw_tags[1:-1]
    tags = ", ".join(part.strip().strip("'\"") for part in raw_tags.split(",") if part.strip())[:500]
    return {
        "title": title,
        "slug": str(metadata.get("slug") or "").strip(),
        "summary": summary,
        "content_html": clean_html(html_content),
        "category": str(metadata.get("category") or "Général")[:120],
        "tags": tags,
        "status": str(metadata.get("status") or "draft"),
        "featured": str(metadata.get("featured") or "").lower() in {"1", "true", "yes", "oui"},
    }


def _apply_import_record(db: Session, record: dict, mode: str, actor: str) -> Article:
    title = str(record.get("title") or "").strip()[:220]
    if not title:
        raise ValueError("Titre manquant.")
    article = _unique_import_article(db, title, mode, str(record.get("slug") or ""))
    article.title = title
    article.summary = str(record.get("summary") or "")[:500]
    if record.get("content_markdown") is not None or str(record.get("format") or "").lower() in {"md", "markdown"}:
        content = str(record.get("content_markdown") or record.get("content") or "")
        import mistune
        markdown_renderer = mistune.create_markdown(escape=True, plugins=["table", "strikethrough", "task_lists", "url"])
        article.content_html = clean_html(markdown_renderer(content))
    else:
        article.content_html = clean_html(str(record.get("content_html") or record.get("content") or ""))
    article.category = str(record.get("category") or "Général")[:120]
    article.tags = str(record.get("tags") or "")[:500]
    article.status = "published" if str(record.get("status", "draft")).lower() in {"published", "publié", "publie", "1", "true"} else "draft"
    article.featured = str(record.get("featured", "")).lower() in {"1", "true", "yes", "oui"}
    article.updated_by = actor[:255]
    db.add(article)
    return article


def _import_single_document(db: Session, filename: str, raw: bytes, mode: str, actor: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".md" or suffix == ".markdown":
        record = _parse_markdown(raw, filename)
        _apply_import_record(db, record, mode, actor)
        db.commit()
        return f"Markdown importé : {record['title']}."

    if suffix == ".docx":
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            raise ValueError("Le document Word n'est pas un fichier DOCX valide.")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if "word/document.xml" not in archive.namelist():
                raise ValueError("Le fichier DOCX ne contient pas de document Word valide.")
            if len(members) > 2000 or sum(item.file_size for item in members) > 120 * 1024 * 1024:
                raise ValueError("Le DOCX contient un volume de données décompressées anormalement élevé.")
        import mammoth
        conversion = mammoth.convert_to_html(io.BytesIO(raw), convert_image=mammoth.images.img_element(_save_docx_image))
        extracted = mammoth.extract_raw_text(io.BytesIO(raw)).value
        plain = re.sub(r"\s+", " ", extracted).strip()
        title = Path(filename).stem.strip()[:220] or "Document Word importé"
        article = _unique_import_article(db, title, mode)
        article.title = title
        article.summary = plain[:480]
        article.content_html = clean_html(conversion.value)
        article.category = "Général"
        article.tags = "Word, DOCX"
        article.status = "draft"
        article.featured = False
        article.updated_by = actor[:255]
        db.add(article)
        db.commit()
        warnings = len(conversion.messages or [])
        return f"DOCX importé : {title}" + (f" ({warnings} avertissement(s) de conversion)." if warnings else ".")

    if suffix == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Le fichier ne possède pas une signature PDF valide.")
        title = Path(filename).stem.strip()[:220] or "Document PDF"
        article = _unique_import_article(db, title, mode)
        db.flush()
        previous_files = []
        for previous in db.query(DocumentAsset).filter(DocumentAsset.article_id == article.id).all():
            previous_files.append(DOCUMENT_DIR / previous.file_name)
            db.delete(previous)
        document_id = uuid.uuid4().hex
        stored_name = f"{document_id}.pdf"
        stored_path = DOCUMENT_DIR / stored_name
        stored_path.write_bytes(raw)
        article.title = title
        article.summary = "Document PDF consultable directement dans le portail FAQ."
        article.content_html = clean_html(
            '<div class="document-intro"><p>Consultez le document dans la visionneuse intégrée ci-dessous.</p></div>'
            f'<iframe class="embedded-pdf-viewer" src="/documents/{document_id}/viewer" title="{escape(title, quote=True)}" width="100%" height="900"></iframe>'
        )
        article.category = "Général"
        article.tags = "PDF, document"
        article.status = "draft"
        article.featured = False
        article.updated_by = actor[:255]
        db.add(DocumentAsset(id=document_id, article_id=article.id, original_name=Path(filename).name[:255], file_name=stored_name, size_bytes=len(raw)))
        try:
            db.commit()
        except Exception:
            db.rollback()
            stored_path.unlink(missing_ok=True)
            raise
        for old_path in previous_files:
            old_path.unlink(missing_ok=True)
        return f"PDF importé : {title} (visionneuse intégrée)."

    raise ValueError(f"Format non pris en charge : {suffix or 'extension absente'}.")


def _records_from_data_file(filename: str, raw: bytes) -> list[dict]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON invalide : {exc}") from exc
        records = payload.get("articles", payload) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise ValueError("Le JSON doit contenir une liste d'articles ou une clé 'articles'.")
        return records
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Le CSV doit être encodé en UTF-8.") from exc
    try:
        dialect = csv.Sniffer().sniff(content[:4096], delimiters=";,\t") if content.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(content), dialect=dialect))


@app.get("/admin/import", response_class=HTMLResponse)
def admin_import_page(request: Request, db: Session = Depends(get_db)):
    """Affiche le formulaire d'import ; le traitement du fichier reste en POST."""
    require_admin(request)
    return render(request, "admin/import.html", db=db)


@app.post("/admin/import")
async def admin_import(
    request: Request,
    csrf: str = Form(...),
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    mode: str = Form("upsert"),
    db: Session = Depends(get_db),
):
    user = require_admin(request)
    check_csrf(request, csrf)
    if mode not in {"upsert", "create"}:
        mode = "upsert"
    uploads = list(files or [])
    if file is not None and file.filename:
        uploads.append(file)
    uploads = [item for item in uploads if item.filename]
    if not uploads:
        return render(request, "admin/import.html", db=db, error="Sélectionnez au moins un fichier.", status_code=422)

    limits = {
        ".pdf": 30 * 1024 * 1024, ".docx": 20 * 1024 * 1024,
        ".csv": 5 * 1024 * 1024, ".json": 5 * 1024 * 1024,
        ".md": 5 * 1024 * 1024, ".markdown": 5 * 1024 * 1024,
        ".zip": 150 * 1024 * 1024,
    }
    total_upload = 0
    total_expanded = 0
    entries: list[tuple[str, bytes]] = []
    errors: list[str] = []
    successes: list[str] = []
    actor = str(user.get("email") or user.get("sub") or "import")
    try:
        for upload in uploads:
            safe_name = Path((upload.filename or "document").replace("\\", "/")).name
            suffix = Path(safe_name).suffix.lower()
            if suffix not in limits:
                errors.append(f"{safe_name} : format non pris en charge.")
                continue
            raw = await upload.read()
            total_upload += len(raw)
            if not raw or len(raw) > limits[suffix]:
                errors.append(f"{safe_name} : fichier vide ou limite dépassée ({limits[suffix] // (1024 * 1024)} Mo).")
                continue
            if total_upload > 180 * 1024 * 1024:
                raise ValueError("La taille cumulée des fichiers envoyés dépasse 180 Mo.")
            if suffix == ".zip":
                if not zipfile.is_zipfile(io.BytesIO(raw)):
                    errors.append(f"{safe_name} : archive ZIP invalide.")
                    continue
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    members = [m for m in archive.infolist() if not m.is_dir() and not m.filename.startswith("__MACOSX/") and not Path(m.filename).name.startswith(".")]
                    if len(members) > 100:
                        raise ValueError(f"{safe_name} : 100 fichiers maximum par archive ZIP.")
                    expanded = sum(m.file_size for m in members)
                    total_expanded += expanded
                    if total_expanded > 250 * 1024 * 1024:
                        raise ValueError("La taille décompressée cumulée des archives dépasse 250 Mo.")
                    for member in members:
                        member_name = Path(member.filename.replace("\\", "/")).name
                        if member_name.lower() in {"readme.md", "lisez-moi.md", "changelog.md", "license.md"}:
                            continue
                        member_suffix = Path(member_name).suffix.lower()
                        if member_suffix not in limits or member_suffix == ".zip":
                            continue
                        if member.file_size > limits[member_suffix]:
                            errors.append(f"{member_name} : taille maximale dépassée dans l'archive.")
                            continue
                        if member.flag_bits & 0x1:
                            errors.append(f"{member_name} : fichier ZIP chiffré non pris en charge.")
                            continue
                        entries.append((member_name, archive.read(member)))
            else:
                entries.append((safe_name, raw))

        if len(entries) > 100:
            raise ValueError("100 fichiers maximum par opération d'import.")
        if not entries and not errors:
            errors.append("Aucun fichier pris en charge n'a été trouvé dans la sélection ou les archives.")

        for entry_name, raw in entries:
            suffix = Path(entry_name).suffix.lower()
            try:
                if suffix in {".csv", ".json"}:
                    records = _records_from_data_file(entry_name, raw)
                    processed = 0
                    skipped = 0
                    for record in records:
                        if not isinstance(record, dict) or not str(record.get("title") or "").strip():
                            skipped += 1
                            continue
                        _apply_import_record(db, record, mode, actor)
                        processed += 1
                    db.commit()
                    successes.append(f"{entry_name} : {processed} article(s) traité(s)" + (f", {skipped} ligne(s) ignorée(s)." if skipped else "."))
                else:
                    successes.append(_import_single_document(db, entry_name, raw, mode, actor))
            except Exception as exc:
                db.rollback()
                errors.append(f"{entry_name} : {str(exc)[:220]}")

        report = {"successes": successes, "errors": errors, "total": len(entries)}
        return render(request, "admin/import.html", db=db, import_report=report, status_code=200 if successes else 422)
    except Exception as exc:
        db.rollback()
        return render(request, "admin/import.html", db=db, error=f"Import impossible : {str(exc)[:240]}", status_code=422)


@app.post("/admin/upload-font")
async def admin_upload_font(request: Request, file: UploadFile = File(...)):
    require_admin(request)
    check_csrf(request, request.headers.get("X-CSRF-Token", ""))
    allowed = {".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf"}
    extension = Path(file.filename or "").suffix.lower()
    if extension not in allowed or (file.content_type and file.content_type not in {allowed[extension], "application/octet-stream"}):
        raise HTTPException(status_code=415, detail="Formats acceptés : WOFF2, WOFF, TTF ou OTF.")
    data = await file.read()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Police vide ou supérieure à 5 Mo.")
    signatures = {".woff2": data.startswith(b"wOF2"), ".woff": data.startswith(b"wOFF"), ".ttf": data.startswith(b"\x00\x01\x00\x00") or data.startswith(b"true"), ".otf": data.startswith(b"OTTO")}
    if not signatures[extension]:
        raise HTTPException(status_code=415, detail="Le contenu du fichier ne correspond pas au format de police annoncé.")
    font_dir = Path(UPLOAD_DIR) / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{extension}"
    (font_dir / filename).write_bytes(data)
    return JSONResponse({"url": f"/static/fonts/{filename}", "name": Path(file.filename or filename).stem[:100]})


@app.post("/admin/upload-image")
async def admin_upload_image(request: Request, file: UploadFile = File(...)):
    require_admin(request)
    check_csrf(request, request.headers.get("X-CSRF-Token", ""))
    allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
    extension = allowed.get(file.content_type or "")
    if not extension:
        raise HTTPException(status_code=415, detail="Format image accepté : PNG, JPEG, WEBP ou GIF.")
    data = await file.read()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image vide ou supérieure à 5 Mo.")
    signatures = {
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".gif": data.startswith((b"GIF87a", b"GIF89a")),
        ".webp": len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if not signatures.get(extension, False):
        raise HTTPException(status_code=415, detail="Le contenu du fichier ne correspond pas au format image annoncé.")
    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(data)
    return JSONResponse({"url": f"/static/uploads/{filename}"})
