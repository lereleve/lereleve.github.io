#!/usr/bin/env python3
"""Le Relevé : construit les données du site à partir des données ouvertes officielles
de l'Assemblée nationale (Licence Ouverte). Python 3.9 ou plus, aucune dépendance."""
import datetime, html, io, json, os, re, statistics, sys, time, urllib.error, urllib.parse, urllib.request, zipfile

R = "https://data.assemblee-nationale.fr/static/openData/repository/"
LEGISLATURES = [
    {"leg": "17", "label": "17e législature", "du": "2024-07-18", "au": None, "requis": True,
     "scrutins": R + "17/loi/scrutins/Scrutins.json.zip",
     "dossiers": R + "17/loi/dossiers_legislatifs/Dossiers_Legislatifs.json.zip"},
    {"leg": "16", "label": "16e législature", "du": "2022-06-28", "au": "2024-06-09",
     "scrutins": R + "16/loi/scrutins/Scrutins.json.zip",
     "dossiers": R + "16/loi/dossiers_legislatifs/Dossiers_Legislatifs.json.zip"},
    {"leg": "15", "label": "15e législature", "du": "2017-06-27", "au": "2022-06-21",
     "scrutins": R + "15/loi/scrutins/Scrutins_XV.json.zip"},
    {"leg": "14", "label": "14e législature", "du": "2012-06-26", "au": "2017-06-20",
     "scrutins": R + "14/loi/scrutins/Scrutins_XIV.json.zip"},
]
ACTEURS = [
    (R + "17/amo/tous_acteurs_mandats_organes_xi_legislature/AMO30_tous_acteurs_tous_mandats_tous_organes_historique.json.zip", True),
    (R + "14/amo/deputes_senateurs_ministres_legislatures_XIV/AMO20_dep_sen_min_tous_mandats_et_organes_XIV.json.zip", False),
]
POLICES = {
    "Newsreader.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/newsreader/Newsreader%5Bopsz,wght%5D.ttf",
    "Newsreader-Italic.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/newsreader/Newsreader-Italic%5Bopsz,wght%5D.ttf",
    "SchibstedGrotesk.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/schibstedgrotesk/SchibstedGrotesk%5Bwght%5D.ttf",
}
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(RACINE, "site")
SEUIL = 20

# ---------- outils ----------
def telecharger(url, requis=True):
    local = os.environ.get("RELEVE_LOCAL")  # dossier de fichiers d'essai, pour tester hors ligne
    if local:
        chemin = os.path.join(local, url.split("/repository/")[-1].replace("/", "_"))
        if os.path.exists(chemin):
            return open(chemin, "rb").read()
        if requis:
            sys.exit(f"ERREUR : fichier d'essai manquant {chemin}")
        print(f"  (essai) absent, ignoré : {chemin}")
        return None
    for essai in range(1, 4):
        try:
            print(f"Téléchargement : {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "LeReleve/2.0 (reutilisation donnees ouvertes)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            print(f"  {len(data) / 1e6:.1f} Mo")
            return data
        except Exception as e:
            print(f"  échec {essai}/3 : {e}")
            time.sleep(10)
    if requis:
        sys.exit(f"ERREUR : impossible de télécharger {url}. Le site en ligne n'est pas modifié.")
    print("  source facultative ignorée")
    return None

def jsons(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    for nom in z.namelist():
        if nom.endswith(".json"):
            try:
                yield json.loads(z.read(nom).decode("utf-8"))
            except Exception as e:
                print(f"  fichier ignoré {nom} : {e}")

def liste(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def txt(x):
    if isinstance(x, dict):
        return x.get("#text") or ""
    return "" if x is None else str(x)

def premier(d, *cles):
    if not isinstance(d, dict):
        return None
    for c in cles:
        if d.get(c) is not None:
            return d[c]
    return None

def entier(x):
    try:
        return int(txt(x))
    except ValueError:
        return 0

def trouver(obj, cle, prof=0):
    """Trouve les objets rangés sous `cle`, que le fichier contienne un objet par fichier ou un export groupé."""
    if prof > 6:
        return
    if isinstance(obj, dict):
        if cle in obj:
            for x in liste(obj[cle]):
                if isinstance(x, dict):
                    yield x
            return
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from trouver(v, cle, prof + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from trouver(v, cle, prof + 1)

def dans(date, debut, fin):
    return (not debut or date >= debut) and (not fin or date <= fin)

def refs(m):
    return [txt(x) for x in liste(premier(m.get("organes") or {}, "organeRef"))]

def mediane(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None

# ---------- ordre habituel des groupes dans l'hémicycle (gauche -> droite du président) ----------
ORDRE = [
    (r"non.inscrit|^ni\b", 99),
    (r"gauche d[ée]mocrate|\bgdr\b", 2),
    (r"insoumis|\blfi\b|^fi\b", 1),
    (r"socialis|\bsrc\b|\bser\b|nouvelle gauche|^ng\b|^soc\b", 4),
    (r"[ée]colog|\becos\b|\becolo\b", 3),
    (r"radical|\brrdp\b", 5),
    (r"libert[ée]s,? ind[ée]pendants|\bliot\b|libert[ée]s et territoires|^lt\b", 6),
    (r"\budi\b|union des d[ée]mocrates et ind[ée]pendants|\buai\b|centriste", 11),
    (r"\bagir\b", 10),
    (r"d[ée]mocrate|modem|^dem\b", 7),
    (r"renaissance|en marche|\blrem\b|\blarem\b|^re\b|^epr\b|ensemble pour la r[ée]publique", 8),
    (r"horizons|^hor\b", 9),
    (r"union des droites|^udr\b|uddplr", 13),
    (r"rassemblement national|^rn\b", 14),
    (r"r[ée]publicains|^lr\b|^dr\b|\bump\b|droite r[ée]publicaine|union pour un mouvement", 12),
]
def rang(sigle, nom):
    t = (sigle + " | " + nom).lower()
    for motif, r in ORDRE:
        if re.search(motif, t) or re.search(motif, sigle.lower()):
            return r
    return 50

# ---------- annuaire ----------
def charger_annuaire():
    acteurs, organes = {}, {}
    for url, requis in ACTEURS:
        data = telecharger(url, requis)
        if not data:
            continue
        for obj in jsons(data):
            for o in trouver(obj, "organe"):
                vm = o.get("viMoDe") or {}
                organes.setdefault(txt(o.get("uid")), {
                    "type": txt(o.get("codeType")), "libelle": txt(o.get("libelle")),
                    "abrev": txt(o.get("libelleAbrev")) or txt(o.get("libelleAbrege")),
                    "debut": txt(vm.get("dateDebut")), "fin": txt(vm.get("dateFin"))})
            for a in trouver(obj, "acteur"):
                uid = txt(a.get("uid"))
                ident = (a.get("etatCivil") or {}).get("ident") or {}
                mandats = liste((a.get("mandats") or {}).get("mandat"))
                if uid in acteurs:
                    acteurs[uid]["mandats"] += mandats
                else:
                    acteurs[uid] = {"civ": txt(ident.get("civ")), "prenom": txt(ident.get("prenom")), "nom": txt(ident.get("nom")),
                                    "hatvp": txt(a.get("uri_hatvp")) or None, "mandats": mandats}
    print(f"Annuaire : {len(acteurs)} personnes, {len(organes)} organes")
    if len(acteurs) < 1000:
        sys.exit("ERREUR : annuaire incomplet. Le site en ligne n'est pas modifié.")
    return acteurs, organes

def profil(uid, a, organes, L):
    leg = L["leg"]
    p = {"id": uid, "civ": a["civ"], "prenom": a["prenom"], "nom": a["nom"], "hatvp": a["hatvp"],
         "periodes": [], "gp": [], "parti": None, "commission": None, "dept": "", "numDept": "", "circ": 0}
    vus = set()
    for m in a["mandats"]:
        t, lg = txt(m.get("typeOrgane")), txt(m.get("legislature"))
        deb = txt(premier(m.get("mandature") or {}, "datePriseFonction")) or txt(m.get("dateDebut"))
        fin = txt(m.get("dateFin")) or None
        cle = (t, deb, fin, tuple(refs(m)))
        if cle in vus:
            continue
        vus.add(cle)
        if t == "ASSEMBLEE" and lg == leg:
            p["periodes"].append([deb, fin])
            lieu = (m.get("election") or {}).get("lieu") or {}
            if lieu:
                p["dept"], p["numDept"], p["circ"] = txt(lieu.get("departement")), txt(lieu.get("numDepartement")), entier(lieu.get("numCirco"))
        elif t == "GP" and lg == leg:
            for o in refs(m):
                p["gp"].append([o, txt(m.get("dateDebut")), fin])
        elif t == "PARPOL" and (not fin or (L["au"] and dans(L["au"], txt(m.get("dateDebut")), fin))):
            for o in refs(m):
                if o in organes:
                    p["parti"] = organes[o]["libelle"]
        elif t == "COMPER" and lg == leg and (not fin or (L["au"] and fin >= L["au"])):
            for o in refs(m):
                if o in organes:
                    p["commission"] = organes[o]["libelle"]
    p["periodes"].sort()
    p["gp"].sort(key=lambda g: g[1] or "")
    fin_leg = L["au"]
    p["actif"] = any(f is None or (fin_leg and f >= fin_leg) for _, f in p["periodes"])
    p["debut"] = p["periodes"][0][0] if p["periodes"] else ""
    return p

# ---------- scrutins ----------
CATS = [(1, ("pours", "pour")), (2, ("contres", "contre")), (3, ("abstentions", "abstention")), (4, ("nonVotants", "nonVotant"))]
POS = {"pour": 1, "contre": 2, "abstention": 3, "abstentions": 3, "nonvotant": 4, "nonvotants": 4}

def votants(bloc):
    if not isinstance(bloc, dict):
        return []
    return [txt(v.get("acteurRef")) for v in liste(bloc.get("votant")) if isinstance(v, dict)]

def charger_scrutins(data, organes=None):
    organes = organes or {}
    out, ecarts, congres = [], 0, 0
    for obj in jsons(data):
        for s in trouver(obj, "scrutin"):
            org = organes.get(txt(s.get("organeRef")), {})
            if org.get("type") == "CONGRES" or "congrès" in org.get("libelle", "").lower():
                congres += 1
                continue
            synth = s.get("syntheseVote") or {}
            dec = synth.get("decompte") or {}
            tv = s.get("typeVote") or {}
            titre = (txt(s.get("titre")) or txt((s.get("objet") or {}).get("libelle"))).strip()
            titre = re.sub(r"\s*\.\s*$", "", titre)
            sc = {"n": entier(s.get("numero")), "d": txt(s.get("dateScrutin"))[:10], "t": txt(tv.get("codeTypeVote")),
                  "tl": txt(tv.get("libelleTypeVote")), "ti": titre,
                  "so": txt((s.get("sort") or {}).get("code")), "dm": txt((s.get("demandeur") or {}).get("texte")),
                  "vo": entier(synth.get("nombreVotants")), "ex": entier(synth.get("suffragesExprimes")), "rq": entier(synth.get("nbrSuffragesRequis")),
                  "po": entier(premier(dec, "pour", "pours")), "co": entier(premier(dec, "contre", "contres")),
                  "ab": entier(premier(dec, "abstentions", "abstention")),
                  "nv": entier(premier(dec, "nonVotants", "nonVotant")) + entier(dec.get("nonVotantsVolontaires")),
                  "groupes": [], "votes": {}, "mises": [], "org": txt(s.get("organeRef"))}
            organe = (s.get("ventilationVotes") or {}).get("organe") or {}
            somme = 0
            for g in liste((organe.get("groupes") or {}).get("groupe")):
                gid = txt(g.get("organeRef"))
                vote = g.get("vote") or {}
                dn, dv = vote.get("decompteNominatif") or {}, vote.get("decompteVoix") or {}
                compte = {1: 0, 2: 0, 3: 0, 4: 0}
                for code, cles in CATS:
                    for ref in votants(premier(dn, *cles)):
                        if ref:
                            sc["votes"][ref] = (code, gid)
                            compte[code] += 1
                if dv:
                    compte = {1: entier(premier(dv, "pour", "pours")), 2: entier(premier(dv, "contre", "contres")),
                              3: entier(premier(dv, "abstentions", "abstention")),
                              4: entier(premier(dv, "nonVotants", "nonVotant")) + entier(dv.get("nonVotantsVolontaires"))}
                somme += compte[1]
                sc["groupes"].append([gid, entier(g.get("nombreMembresGroupe")), POS.get(txt(vote.get("positionMajoritaire")).lower(), 0),
                                      compte[1], compte[2], compte[3], compte[4]])
            if somme != sc["po"]:
                ecarts += 1
            mp = s.get("miseAuPoint") or {}
            for code, cles in CATS:
                for ref in votants(premier(mp, *cles)):
                    if ref:
                        sc["mises"].append([ref, code])
            if sc["n"] and sc["d"]:
                out.append(sc)
    compte_org = {}
    for sc in out:
        compte_org[sc["org"]] = compte_org.get(sc["org"], 0) + 1
    principal = max(compte_org, key=compte_org.get) if compte_org else ""
    autres = [sc for sc in out if sc["org"] and sc["org"] != principal]
    if autres:
        congres += len(autres)
        out = [sc for sc in out if not sc["org"] or sc["org"] == principal]
    uniques = {}
    for sc in out:
        uniques.setdefault(sc["n"], sc)
    out = sorted(uniques.values(), key=lambda x: x["n"])
    if congres:
        print(f"  {congres} scrutin(s) du Congrès du Parlement écarté(s)")
    print(f"  scrutins : {len(out)} ; votes nominatifs : {sum(len(s['votes']) for s in out)}" + (f" ; {ecarts} totaux de groupe différents du total officiel" if ecarts else ""))
    return out

# ---------- dossiers législatifs (lois) ----------
def actes(noeud, prof=0):
    if prof > 12:
        return
    for a in liste((noeud.get("actesLegislatifs") or {}).get("acteLegislatif")):
        if isinstance(a, dict):
            yield a
            yield from actes(a, prof + 1)

CODES_UTILES = re.compile(r"(DEPOT|DEC|PROM|PUB|CONCLUSION|SAISIE-CC)$")
def charger_lois(data, numeros, leg):
    lois = []
    for obj in jsons(data):
        for d in trouver(obj, "dossierParlementaire"):
            titre_d = d.get("titreDossier") or {}
            proc = txt((d.get("procedureParlementaire") or {}).get("libelle"))
            if "résolution" in proc.lower():
                continue
            etapes, scr, prom, cc = [], set(), None, None
            for a in actes(d):
                code = txt(a.get("codeActe"))
                lib = txt(premier(a.get("libelleActe") or {}, "nomCanonique", "libelleCourt"))
                date = txt(a.get("dateActe"))[:10]
                for v in liste(premier(a.get("voteRefs") or {}, "voteRef")):
                    m = re.search(r"V(\d+)$", txt(v))
                    if m and int(m.group(1)) in numeros:
                        scr.add(int(m.group(1)))
                jo = a.get("infoJO") or {}
                if code.startswith("PROM") and (jo or a.get("titreLoi")):
                    prom = {"date": txt(jo.get("dateJO"))[:10] or date, "url": txt(jo.get("urlLegifrance")) or None,
                            "titre": txt(a.get("titreLoi")) or None}
                if "CONCLUSION" in code and code.startswith("CC"):
                    cc = {"date": date, "lib": txt((a.get("statutConclusion") or {}).get("libelle")) or lib, "url": txt(a.get("urlConclusion")) or None}
                if date and CODES_UTILES.search(code):
                    etapes.append([code, lib, date])
            if not prom and not scr:
                continue
            vu, et = set(), []
            for e in sorted(etapes, key=lambda x: x[2]):
                k = (e[0], e[2])
                if k not in vu:
                    vu.add(k)
                    et.append(e)
            lois.append({"id": txt(d.get("uid")), "titre": txt(titre_d.get("titre")), "chemin": txt(titre_d.get("titreChemin")) or None,
                         "proc": proc, "etapes": et[:24], "prom": prom, "cc": cc, "scrutins": sorted(scr)})
    lois.sort(key=lambda l: (l["prom"] or {}).get("date") or (l["etapes"][-1][2] if l["etapes"] else ""), reverse=True)
    print(f"  lois et textes suivis : {len(lois)} (dont {sum(1 for l in lois if l['prom'])} promulguées)")
    return lois


# ---------- photos libres (Wikidata + Wikimedia Commons) ----------
UA = "LeReleve/2.0 (https://lereleve.github.io ; reutilisation de donnees ouvertes)"
LICENCES_LIBRES = re.compile(r"^(cc0|public domain|pd|domaine public|cc[ -]by(-sa)?([ -][\d.]+)?)", re.I)
def obtenir(url, accept=None, timeout=120):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()

def lire_sparql(donnees, ids):
    fichiers = {}
    for b in donnees.get("results", {}).get("bindings", []):
        an = "PA" + re.sub(r"\D", "", b.get("an", {}).get("value", ""))
        img = b.get("img", {}).get("value", "")
        if an in ids and img and an not in fichiers:
            fichiers[an] = urllib.parse.unquote(img.rsplit("/", 1)[-1]).replace("_", " ")
    return fichiers

def lire_commons(donnees):
    q = donnees.get("query", {})
    renomme = {n["to"]: n["from"] for n in q.get("normalized", [])}
    infos = {}
    for p in q.get("pages", []):
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        auteur = html.unescape(re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))).strip()
        auteur = re.sub(r"\s+", " ", auteur)[:120] or "Auteur non précisé"
        libre = bool(LICENCES_LIBRES.search(lic.strip())) and not re.search(r"\b(nc|nd)\b", lic.lower())
        titre = p.get("title", "")
        infos[renomme.get(titre, titre)] = {"libre": libre, "licence": lic, "auteur": auteur,
                                            "vignette": ii.get("thumburl"), "page": ii.get("descriptionurl")}
    return infos

def image_valide(chemin):
    try:
        if os.path.getsize(chemin) < 1500:
            return False
        with open(chemin, "rb") as fh:
            tete = fh.read(12)
        return tete[:3] == b"\xff\xd8\xff" or tete[:8] == b"\x89PNG\r\n\x1a\n" or tete[:4] == b"GIF8" or (tete[:4] == b"RIFF" and tete[8:12] == b"WEBP")
    except OSError:
        return False

def telecharger_image(url):
    for essai in range(4):
        try:
            data = obtenir(url, timeout=60)
            if len(data) >= 1500:
                return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                attente = int(e.headers.get("Retry-After") or 0) or 5 * (essai + 1)
                time.sleep(min(attente, 60))
                continue
            return None
        except Exception:
            time.sleep(2)
    return None

def photos_libres(ids):
    """Retourne {PA…: {f, a, l, u}} ; conserve les vignettes déjà téléchargées (cache)."""
    dossier = os.path.join(SITE, "photos")
    os.makedirs(dossier, exist_ok=True)
    chemin_credits = os.path.join(dossier, "credits.json")
    try:
        credits = json.load(open(chemin_credits, encoding="utf-8"))
    except Exception:
        credits = {}
    if os.environ.get("RELEVE_LOCAL"):
        return credits
    try:
        requete = "SELECT ?an ?img WHERE { ?p wdt:P4123 ?an ; wdt:P18 ?img . }"
        brut = obtenir("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(requete), "application/sparql-results+json")
        fichiers = lire_sparql(json.loads(brut), ids)
        print(f"Photos : {len(fichiers)} députés ont une image sur Wikidata")
        noms = sorted(set(fichiers.values()))
        infos = {}
        for i in range(0, len(noms), 40):
            titres = "|".join("File:" + n for n in noms[i:i + 40])
            url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2&prop=imageinfo"
                   "&iiprop=url|extmetadata&iiurlwidth=250&titles=" + urllib.parse.quote(titres))
            infos.update(lire_commons(json.loads(obtenir(url))))
            time.sleep(0.2)
        nouveaux = refus = echecs = 0
        for an, nom in fichiers.items():
            info = infos.get("File:" + nom) or infos.get("Fichier:" + nom)
            if not info or not info["libre"] or not info["vignette"]:
                refus += 1
                credits.pop(an, None)
                continue
            ext = os.path.splitext(info["vignette"].split("?")[0])[1].lower() or ".jpg"
            f = f"photos/{an}{ext}"
            chemin = os.path.join(SITE, f)
            if not image_valide(chemin):
                contenu = telecharger_image(info["vignette"])
                if not contenu:
                    echecs += 1
                    credits.pop(an, None)
                    continue
                with open(chemin + ".tmp", "wb") as fh:
                    fh.write(contenu)
                os.replace(chemin + ".tmp", chemin)
                nouveaux += 1
                time.sleep(0.25)
            credits[an] = {"f": f, "a": info["auteur"], "l": info["licence"], "u": info["page"]}
        json.dump(credits, open(chemin_credits, "w", encoding="utf-8"), ensure_ascii=False)
        credits = {k: v for k, v in credits.items() if image_valide(os.path.join(SITE, v["f"]))}
        json.dump(credits, open(chemin_credits, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {len(credits)} photos sous licence libre ({nouveaux} nouvelles) ; {refus} écartées (licence non libre ou introuvable) ; {echecs} téléchargements à reprendre au prochain passage")
    except Exception as e:
        print(f"Photos : collecte interrompue ({e}), le site est construit sans nouvelles photos")
    return credits

# ---------- calcul d'une législature ----------
def periodes(L, aujourd_hui):
    fin_leg = L["au"] or aujourd_hui
    res, debut, annee = [], L["du"], int(L["du"][:4])
    while debut <= fin_leg:
        fin = min(f"{annee + 1}-09-30", fin_leg)
        res.append({"id": len(res), "label": f"{annee}-{annee + 1}", "du": debut, "au": fin})
        annee += 1
        debut = f"{annee}-10-01"
    return res

def construire_legislature(L, acteurs, organes, aujourd_hui, credits=None):
    credits = credits or {}
    print(f"\n== {L['label']} ==")
    data = telecharger(L["scrutins"], L.get("requis", False))
    if not data:
        return None
    scrutins = charger_scrutins(data, organes)
    del data
    if len(scrutins) < 100:
        if L.get("requis"):
            sys.exit("ERREUR : trop peu de scrutins lus. Le site en ligne n'est pas modifié.")
        print("  législature ignorée (trop peu de scrutins lus)")
        return None
    per = periodes(L, aujourd_hui)
    leg = L["leg"]
    ids = {uid for uid, a in acteurs.items() if any(txt(m.get("typeOrgane")) == "ASSEMBLEE" and txt(m.get("legislature")) == leg for m in a["mandats"])}
    for s in scrutins:
        ids.update(s["votes"].keys())
    deputes = []
    for uid in ids:
        a = acteurs.get(uid) or {"civ": "", "prenom": "", "nom": uid, "hatvp": None, "mandats": []}
        deputes.append(profil(uid, a, organes, L))
    deputes.sort(key=lambda d: (d["nom"], d["prenom"]))
    index = {d["id"]: i for i, d in enumerate(deputes)}
    # groupe réellement enregistré dans chaque scrutin : segments [premier n°, dernier n°, organe]
    for d in deputes:
        d["seg"] = []
    for s in scrutins:
        for ref, (code, gid) in s["votes"].items():
            d = deputes[index[ref]]
            if d["seg"] and d["seg"][-1][2] == gid:
                d["seg"][-1][1] = s["n"]
            else:
                d["seg"].append([s["n"], s["n"], gid])
    def groupe_final(d):
        cur = [g for g, deb, fin in d["gp"] if not fin or (L["au"] and fin >= L["au"])]
        if cur:
            return cur[-1]
        if d["seg"]:
            return d["seg"][-1][2]
        return d["gp"][-1][0] if d["gp"] else None
    actifs = [d for d in deputes if d["actif"]]
    gids = []
    for d in actifs:
        g = groupe_final(d)
        if g and g not in gids:
            gids.append(g)
    for s in scrutins:
        for b in s["groupes"]:
            if b[0] not in gids:
                gids.append(b[0])
    groupes = []
    for gid in gids:
        o = organes.get(gid, {})
        sigle = o.get("abrev") or o.get("libelle") or gid
        nom = o.get("libelle") or gid
        g = {"id": gid, "sigle": sigle, "nom": nom, "debut": o.get("debut") or None, "fin": o.get("fin") or None,
             "rang": rang(sigle, nom)}
        g["ni"] = g["rang"] == 99
        g["actif"] = not g["fin"] or (L["au"] is not None and g["fin"] >= L["au"])
        g["effectif"] = sum(1 for d in actifs if groupe_final(d) == gid)
        groupes.append(g)
    groupes.sort(key=lambda g: (not g["actif"], g["rang"], -g["effectif"]))
    gi = {g["id"]: i for i, g in enumerate(groupes)}
    ni = {g["id"] for g in groupes if g["ni"]}
    # indicateurs individuels
    K = len(per)
    for d in deputes:
        d["st"] = [{"el": 0, "vo": 0, "elS": 0, "voS": 0, "alN": 0, "al": 0} for _ in range(K + 1)]
    for s in scrutins:
        k = next((p["id"] for p in per if p["du"] <= s["d"] <= p["au"]), K - 1)
        pos = {b[0]: b[2] for b in s["groupes"]}
        sol = s["t"] == "SPS"
        for d in deputes:
            if not any(dans(s["d"], deb, fin) for deb, fin in d["periodes"]):
                continue
            code, g = s["votes"].get(d["id"], (0, None))
            if code == 4:
                continue
            for st in (d["st"][k], d["st"][K]):
                st["el"] += 1
                if sol:
                    st["elS"] += 1
                if code in (1, 2, 3):
                    st["vo"] += 1
                    if sol:
                        st["voS"] += 1
                    if g and g not in ni and pos.get(g) in (1, 2, 3):
                        st["alN"] += 1
                        st["al"] += code == pos.get(g)
    for d in deputes:
        for st in d["st"]:
            st["part"] = round(st["vo"] / st["el"], 4) if st["el"] else None
            st["partS"] = round(st["voS"] / st["elS"], 4) if st["elS"] else None
            st["align"] = round(st["al"] / st["alN"], 4) if st["alN"] else None
    medianes = []
    for k in range(K + 1):
        ok = [d for d in actifs if d["st"][k]["el"] >= SEUIL]
        medianes.append({c: mediane([d["st"][k][c] for d in ok]) for c in ("part", "partS", "align")})
    # indicateurs de groupe
    positions = [{b[0]: b[2] for b in s["groupes"]} for s in scrutins]
    for g in groupes:
        rice = [abs(b[3] - b[4]) / (b[3] + b[4]) for s in scrutins for b in s["groupes"] if b[0] == g["id"] and b[3] + b[4] > 0]
        g["rice"] = None if g["ni"] or not rice else round(sum(rice) / len(rice), 4)
        membres = [d for d in actifs if groupe_final(d) == g["id"]]
        g["partMed"] = mediane([d["st"][K]["part"] for d in membres if d["st"][K]["el"] >= SEUIL])
        g["partSMed"] = mediane([d["st"][K]["partS"] for d in membres if d["st"][K]["elS"] >= 5])
        partis = {}
        for d in membres:
            k2 = d["parti"] or "Aucun parti déclaré"
            partis[k2] = partis.get(k2, 0) + 1
        g["partis"] = sorted(partis.items(), key=lambda x: -x[1])
        g["accord"] = {}
        for h in groupes:
            if g["ni"] or h["ni"] or g is h:
                continue
            n = a2 = 0
            for p in positions:
                x, y = p.get(g["id"]), p.get(h["id"])
                if x in (1, 2, 3) and y in (1, 2, 3):
                    n += 1
                    a2 += x == y
            g["accord"][h["id"]] = round(a2 / n, 4) if n >= 30 else None
    # lois
    lois = []
    if L.get("dossiers"):
        dd = telecharger(L["dossiers"], False)
        if dd:
            try:
                lois = charger_lois(dd, {s["n"] for s in scrutins}, leg)
            except Exception as e:
                print(f"  dossiers législatifs ignorés : {e}")
    # sortie compacte
    sortie = []
    for s in scrutins:
        v = []
        for d in deputes:
            code = s["votes"].get(d["id"], (None, None))[0]
            v.append(str(code) if code else ("0" if any(dans(s["d"], deb, fin) for deb, fin in d["periodes"]) else "-"))
        sortie.append({"n": s["n"], "d": s["d"], "t": s["t"], "tl": s["tl"], "ti": s["ti"], "so": s["so"], "dm": s["dm"],
                       "vo": s["vo"], "ex": s["ex"], "rq": s["rq"], "po": s["po"], "co": s["co"], "ab": s["ab"], "nv": s["nv"],
                       "g": [[gi.get(b[0], -1)] + b[1:] for b in s["groupes"]],
                       "m": [[index[r], c] for r, c in s["mises"] if r in index], "v": "".join(v)})
    donnees = {
        "legislature": leg, "label": L["label"], "du": L["du"], "au": L["au"], "courante": L["au"] is None,
        "maj": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "sources": {"scrutins": L["scrutins"], "acteurs": ACTEURS[0][0], "dossiers": L.get("dossiers"), "licence": "Licence Ouverte / Open Licence (Etalab)"},
        "periodes": per, "medianes": medianes, "groupes": groupes, "lois": lois,
        "deputes": [{"id": d["id"], "civ": d["civ"], "prenom": d["prenom"], "nom": d["nom"], "dept": d["dept"], "numDept": d["numDept"],
                     "circ": d["circ"], "actif": d["actif"], "debut": d["debut"], "periodes": d["periodes"],
                     "groupe": gi.get(groupe_final(d) or "", -1), "seg": [[a, b, gi.get(c, -1)] for a, b, c in d["seg"]],
                     "parti": d["parti"], "commission": d["commission"], "hatvp": d["hatvp"], "photo": credits.get(d["id"]), "st": d["st"]} for d in deputes],
        "scrutins": sortie,
    }
    nom = f"data-{leg}.json"
    with open(os.path.join(SITE, nom), "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  écrit : {nom} ({os.path.getsize(os.path.join(SITE, nom)) / 1e6:.1f} Mo) ; groupes : " + ", ".join(f"{g['sigle']} {g['effectif']}" for g in groupes if g["actif"]))
    return {"leg": leg, "label": L["label"], "du": L["du"], "au": L["au"], "fichier": nom, "nb": len(scrutins),
            "premier": scrutins[0]["d"], "dernier": scrutins[-1]["d"], "deputes": len(actifs), "lois": len(lois)}

# ---------- contenus éditoriaux ----------
def verifier_contenus():
    dossier = os.path.join(SITE, "contenu")
    erreurs = []
    for nom in ("lois.json", "corrections.json", "site.json"):
        chemin = os.path.join(dossier, nom)
        if not os.path.exists(chemin):
            erreurs.append(f"{nom} : fichier manquant")
            continue
        try:
            contenu = json.load(open(chemin, encoding="utf-8"))
        except json.JSONDecodeError as e:
            erreurs.append(f"{nom}, ligne {e.lineno}, colonne {e.colno} : {e.msg} (virgule, guillemet ou crochet manquant ?)")
            continue
        if nom == "lois.json":
            for i, t in enumerate(contenu or []):
                if isinstance(t, dict) and t.get("publie"):
                    for champ in ("titre_officiel", "phrase", "auteur", "verif"):
                        if not t.get(champ):
                            erreurs.append(f"lois.json, fiche {i + 1} : le champ « {champ} » est vide")
                    if t.get("auteur") and t.get("auteur") == t.get("verif"):
                        erreurs.append(f"lois.json, fiche {i + 1} : l'auteur et le vérificateur doivent être deux personnes différentes")
    if erreurs:
        print("\nERREURS DANS LES CONTENUS (le site en ligne n'est pas modifié) :")
        for x in erreurs:
            print("  - " + x)
        sys.exit(1)
    print("Contenus éditoriaux vérifiés.")

def polices():
    dossier = os.path.join(SITE, "fonts")
    os.makedirs(dossier, exist_ok=True)
    for nom, url in POLICES.items():
        chemin = os.path.join(dossier, nom)
        if os.path.exists(chemin) or os.environ.get("RELEVE_LOCAL"):
            continue
        data = telecharger(url, False)
        if data:
            open(chemin, "wb").write(data)

def main():
    verifier_contenus()
    polices()
    acteurs, organes = charger_annuaire()
    aujourd_hui = datetime.date.today().isoformat()
    legs = {L["leg"] for L in LEGISLATURES}
    ids = {uid for uid, a in acteurs.items() if any(txt(m.get("typeOrgane")) == "ASSEMBLEE" and txt(m.get("legislature")) in legs for m in a["mandats"])}
    credits = photos_libres(ids)
    index = []
    for L in LEGISLATURES:
        r = construire_legislature(L, acteurs, organes, aujourd_hui, credits)
        if r:
            index.append(r)
    with open(os.path.join(SITE, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"maj": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "legislatures": index}, f, ensure_ascii=False)
    print("\nTerminé : " + ", ".join(f"{x['label']} ({x['nb']} scrutins)" for x in index))

if __name__ == "__main__":
    main()
