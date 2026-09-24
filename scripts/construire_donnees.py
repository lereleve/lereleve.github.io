#!/usr/bin/env python3
"""Le Relevé : construit site/data.json à partir des données ouvertes officielles
de l'Assemblée nationale (Licence Ouverte). Aucune dépendance : Python 3.9 ou plus.

Sources :
  - Scrutins publics de la législature (vote de chaque député)
  - Historique des députés (état civil, mandats, groupes, partis, commissions)
"""
import datetime, io, json, os, statistics, sys, time, urllib.request, zipfile

LEG = "17"
DEBUT_LEG = "2024-07-18"
BASE = "https://data.assemblee-nationale.fr/static/openData/repository/" + LEG
URL_SCRUTINS = BASE + "/loi/scrutins/Scrutins.json.zip"
URL_ACTEURS = BASE + "/amo/tous_acteurs_mandats_organes_xi_legislature/AMO30_tous_acteurs_tous_mandats_tous_organes_historique.json.zip"
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTIE = os.path.join(RACINE, "site", "data.json")
SEUIL_PERIODE, SEUIL_TOTAL = 20, 30

# ---------- outils ----------
def telecharger(url, variable_locale):
    chemin = os.environ.get(variable_locale)  # permet un test hors ligne
    if chemin:
        print(f"Lecture locale : {chemin}")
        return open(chemin, "rb").read()
    for essai in range(1, 4):
        try:
            print(f"Téléchargement : {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "LeReleve/1.0 (reutilisation donnees ouvertes)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            print(f"  {len(data)/1e6:.1f} Mo reçus")
            return data
        except Exception as e:
            print(f"  échec {essai}/3 : {e}")
            time.sleep(15)
    sys.exit(f"ERREUR : impossible de télécharger {url}")

def fichiers_json(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    for nom in z.namelist():
        if nom.endswith(".json"):
            try:
                yield nom, json.loads(z.read(nom).decode("utf-8"))
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

def dans(date, debut, fin):
    return (not debut or date >= debut) and (not fin or date <= fin)

def refs_organes(m):
    return [txt(x) for x in liste(premier(m.get("organes") or {}, "organeRef"))]

# ---------- acteurs et organes ----------
def charger_acteurs():
    acteurs, organes = {}, {}
    for nom, obj in fichiers_json(telecharger(URL_ACTEURS, "RELEVE_ACTEURS_ZIP")):
        if "organe" in obj:
            o = obj["organe"]
            vm = o.get("viMoDe") or {}
            organes[txt(o.get("uid"))] = {
                "type": txt(o.get("codeType")), "libelle": txt(o.get("libelle")),
                "abrev": txt(o.get("libelleAbrev")) or txt(o.get("libelleAbrege")),
                "leg": txt(o.get("legislature")), "debut": txt(vm.get("dateDebut")), "fin": txt(vm.get("dateFin"))}
        elif "acteur" in obj:
            a = obj["acteur"]
            ident = (a.get("etatCivil") or {}).get("ident") or {}
            acteurs[txt(a.get("uid"))] = {
                "civ": txt(ident.get("civ")), "prenom": txt(ident.get("prenom")), "nom": txt(ident.get("nom")),
                "hatvp": txt(a.get("uri_hatvp")) or None,
                "mandats": liste((a.get("mandats") or {}).get("mandat"))}
    print(f"Acteurs : {len(acteurs)} ; organes : {len(organes)}")
    if len(acteurs) < 1000 or len(organes) < 100:
        sys.exit("ERREUR : l'annuaire des acteurs semble incomplet, rien n'est publié.")
    return acteurs, organes

def profil_depute(uid, a, organes):
    p = {"id": uid, "civ": a["civ"], "prenom": a["prenom"], "nom": a["nom"], "hatvp": a["hatvp"],
         "periodes": [], "groupes": [], "parti": None, "commission": None, "dept": "", "numDept": "", "circ": 0}
    for m in a["mandats"]:
        t, leg = txt(m.get("typeOrgane")), txt(m.get("legislature"))
        deb = txt(premier(m.get("mandature") or {}, "datePriseFonction")) or txt(m.get("dateDebut"))
        fin = txt(m.get("dateFin")) or None
        if t == "ASSEMBLEE" and leg == LEG:
            p["periodes"].append([deb, fin])
            lieu = (m.get("election") or {}).get("lieu") or {}
            if lieu:
                p["dept"], p["numDept"], p["circ"] = txt(lieu.get("departement")), txt(lieu.get("numDepartement")), entier(lieu.get("numCirco"))
        elif t == "GP" and leg == LEG:
            for o in refs_organes(m):
                p["groupes"].append([o, txt(m.get("dateDebut")), fin])
        elif t == "PARPOL" and not fin:
            for o in refs_organes(m):
                if o in organes:
                    p["parti"] = organes[o]["libelle"]
        elif t == "COMPER" and leg == LEG and not fin:
            for o in refs_organes(m):
                if o in organes:
                    p["commission"] = organes[o]["libelle"]
    p["periodes"].sort()
    p["groupes"].sort(key=lambda g: g[1] or "")
    p["actif"] = any(f is None for _, f in p["periodes"])
    p["debut"] = p["periodes"][0][0] if p["periodes"] else ""
    return p

# ---------- scrutins ----------
CATS = [(1, ("pours", "pour")), (2, ("contres", "contre")), (3, ("abstentions", "abstention")), (4, ("nonVotants", "nonVotant"))]
POS = {"pour": 1, "contre": 2, "abstention": 3, "abstentions": 3, "nonVotant": 4, "nonVotants": 4}

def votants(bloc):
    if not isinstance(bloc, dict):
        return []
    return [txt(v.get("acteurRef")) for v in liste(bloc.get("votant")) if isinstance(v, dict)]

def charger_scrutins():
    out, ecarts = [], 0
    for nom, obj in fichiers_json(telecharger(URL_SCRUTINS, "RELEVE_SCRUTINS_ZIP")):
        s = obj.get("scrutin")
        if not s:
            continue
        synth = s.get("syntheseVote") or {}
        dec = synth.get("decompte") or {}
        tv = s.get("typeVote") or {}
        sc = {"n": entier(s.get("numero")), "d": txt(s.get("dateScrutin")), "t": txt(tv.get("codeTypeVote")),
              "tl": txt(tv.get("libelleTypeVote")), "ti": txt(s.get("titre")) or txt((s.get("objet") or {}).get("libelle")),
              "so": txt((s.get("sort") or {}).get("code")), "dm": txt((s.get("demandeur") or {}).get("texte")),
              "vo": entier(synth.get("nombreVotants")), "ex": entier(synth.get("suffragesExprimes")), "rq": entier(synth.get("nbrSuffragesRequis")),
              "po": entier(premier(dec, "pour", "pours")), "co": entier(premier(dec, "contre", "contres")),
              "ab": entier(premier(dec, "abstentions", "abstention")), "nv": entier(premier(dec, "nonVotants", "nonVotant")) + entier(dec.get("nonVotantsVolontaires")),
              "groupes": [], "votes": {}, "mises": []}
        organe = (s.get("ventilationVotes") or {}).get("organe") or {}
        somme_pour = 0
        for g in liste((organe.get("groupes") or {}).get("groupe")):
            gid = txt(g.get("organeRef"))
            vote = g.get("vote") or {}
            dn = vote.get("decompteNominatif") or {}
            dv = vote.get("decompteVoix") or {}
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
            somme_pour += compte[1]
            sc["groupes"].append([gid, entier(g.get("nombreMembresGroupe")), POS.get(txt(vote.get("positionMajoritaire")), 0),
                                  compte[1], compte[2], compte[3], compte[4]])
        if somme_pour != sc["po"]:
            ecarts += 1
        mp = s.get("miseAuPoint") or {}
        for code, cles in CATS:
            for ref in votants(premier(mp, *cles)):
                if ref:
                    sc["mises"].append([ref, code])
        if sc["n"] and sc["d"]:
            out.append(sc)
    out.sort(key=lambda x: x["n"])
    print(f"Scrutins : {len(out)} ; votes nominatifs : {sum(len(s['votes']) for s in out)}")
    if ecarts:
        print(f"  avertissement : {ecarts} scrutins où la somme des groupes diffère du total officiel")
    if len(out) < 100:
        sys.exit("ERREUR : trop peu de scrutins lus, le format a peut-être changé. Rien n'est publié.")
    return out


# ---------- vérification des contenus éditoriaux ----------
def verifier_contenus(numeros, deputes_ids):
    dossier = os.path.join(RACINE, "site", "contenu")
    erreurs = []
    donnees = {}
    for nom in ("lois.json", "revirements.json", "corrections.json", "site.json"):
        chemin = os.path.join(dossier, nom)
        if not os.path.exists(chemin):
            erreurs.append(f"{nom} : fichier manquant")
            continue
        try:
            donnees[nom] = json.load(open(chemin, encoding="utf-8"))
        except json.JSONDecodeError as e:
            erreurs.append(f"{nom}, ligne {e.lineno}, colonne {e.colno} : {e.msg} (virgule, guillemet ou crochet manquant ?)")
    for i, t in enumerate(donnees.get("lois.json", []) or []):
        if not isinstance(t, dict):
            erreurs.append(f"lois.json, fiche {i + 1} : format inattendu"); continue
        for champ in ("id", "usage", "titre", "phrase", "auteur", "verif"):
            if not t.get(champ):
                erreurs.append(f"lois.json, fiche {i + 1} : le champ « {champ} » est vide")
        if t.get("scrutin") and int(t["scrutin"]) not in numeros:
            erreurs.append(f"lois.json, fiche « {t.get('id')} » : le scrutin n° {t['scrutin']} n'existe pas")
    for i, e in enumerate(donnees.get("revirements.json", []) or []):
        if not isinstance(e, dict):
            erreurs.append(f"revirements.json, fiche {i + 1} : format inattendu"); continue
        if not e.get("publie"):
            continue
        for champ in ("id", "titre", "depute", "scrutin", "statut", "comparabilite", "publie_le", "auteur", "verif"):
            if not e.get(champ):
                erreurs.append(f"revirements.json, fiche {i + 1} : le champ « {champ} » est vide")
        if e.get("auteur") and e.get("auteur") == e.get("verif"):
            erreurs.append(f"revirements.json, fiche « {e.get('id')} » : l'auteur et le vérificateur doivent être deux personnes différentes")
        if e.get("depute") and e["depute"] not in deputes_ids:
            erreurs.append(f"revirements.json, fiche « {e.get('id')} » : le député {e['depute']} est introuvable")
        if e.get("scrutin") and int(e["scrutin"]) not in numeros:
            erreurs.append(f"revirements.json, fiche « {e.get('id')} » : le scrutin n° {e['scrutin']} n'existe pas")
        dec = e.get("declaration") or {}
        if not dec.get("url"):
            erreurs.append(f"revirements.json, fiche « {e.get('id')} » : la déclaration n'a pas de lien vers sa source")
        rep = e.get("reponse") or {}
        if not rep.get("sollicite"):
            erreurs.append(f"revirements.json, fiche « {e.get('id')} » : la date de sollicitation du député manque")
    if erreurs:
        print("\nERREURS DANS LES CONTENUS (le site en ligne n'est pas modifié) :")
        for x in erreurs:
            print("  - " + x)
        sys.exit(1)
    print("Contenus éditoriaux vérifiés : " + ", ".join(f"{k} ({len(v) if isinstance(v, list) else 'ok'})" for k, v in donnees.items()))

# ---------- calculs ----------
def periodes_parlementaires(aujourd_hui):
    res, debut, annee = [], DEBUT_LEG, int(DEBUT_LEG[:4])
    while debut <= aujourd_hui:
        fin = f"{annee + 1}-09-30"
        res.append({"id": len(res), "label": f"{annee}-{annee + 1}", "du": debut, "au": fin})
        annee += 1
        debut = f"{annee}-10-01"
    return res

def periode_de(date, periodes):
    for p in periodes:
        if p["du"] <= date <= p["au"]:
            return p["id"]
    return len(periodes) - 1

def rang_centile(valeur, triees):
    if valeur is None or not triees:
        return None
    bas = sum(1 for v in triees if v < valeur)
    eg = sum(1 for v in triees if v == valeur)
    return round((bas + eg / 2) / len(triees) * 100)

def mediane(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None

def construire():
    acteurs, organes = charger_acteurs()
    scrutins = charger_scrutins()
    aujourd_hui = datetime.date.today().isoformat()
    periodes = periodes_parlementaires(aujourd_hui)

    # députés : tous ceux qui ont un mandat dans la législature, plus tout votant inconnu
    refs = {uid for uid, a in acteurs.items() if any(txt(m.get("typeOrgane")) == "ASSEMBLEE" and txt(m.get("legislature")) == LEG for m in a["mandats"])}
    for s in scrutins:
        refs.update(s["votes"].keys())
    deputes = []
    for uid in refs:
        a = acteurs.get(uid) or {"civ": "", "prenom": "", "nom": uid, "hatvp": None, "mandats": []}
        deputes.append(profil_depute(uid, a, organes))
    deputes.sort(key=lambda d: (d["nom"], d["prenom"]))
    index = {d["id"]: i for i, d in enumerate(deputes)}
    actifs = [d for d in deputes if d["actif"]]
    print(f"Députés de la législature : {len(deputes)} ; en exercice : {len(actifs)}")
    if len(actifs) < 500:
        sys.exit("ERREUR : moins de 500 députés en exercice, rien n'est publié.")

    # groupes
    def est_ni(gid):
        o = organes.get(gid, {})
        return o.get("abrev", "").upper() == "NI" or "non inscrit" in o.get("libelle", "").lower()
    gids = []
    for d in actifs:
        for g, deb, fin in d["groupes"]:
            if not fin and g not in gids:
                gids.append(g)
    for s in scrutins:
        for g in s["groupes"]:
            if g[0] not in gids:
                gids.append(g[0])
    groupes = []
    for gid in gids:
        o = organes.get(gid, {})
        groupes.append({"id": gid, "sigle": o.get("abrev") or o.get("libelle") or gid, "nom": o.get("libelle") or gid,
                        "actif": not o.get("fin"), "debut": o.get("debut"), "fin": o.get("fin") or None, "ni": est_ni(gid)})
    groupe_actuel = {}
    for d in actifs:
        cur = [g for g, deb, fin in d["groupes"] if not fin]
        groupe_actuel[d["id"]] = cur[-1] if cur else (d["groupes"][-1][0] if d["groupes"] else None)
    for g in groupes:
        g["effectif"] = sum(1 for d in actifs if groupe_actuel.get(d["id"]) == g["id"])
    groupes.sort(key=lambda g: (g["ni"], not g["actif"], -g["effectif"], g["sigle"]))
    gindex = {g["id"]: i for i, g in enumerate(groupes)}

    # statistiques par député
    for d in deputes:
        d["st"] = [{"el": 0, "vo": 0, "alN": 0, "al": 0} for _ in periodes] + [{"el": 0, "vo": 0, "alN": 0, "al": 0}]
    ni = {g["id"] for g in groupes if g["ni"]}
    for s in scrutins:
        k = periode_de(s["d"], periodes)
        pos = {g[0]: g[2] for g in s["groupes"]}
        for d in deputes:
            if not any(dans(s["d"], deb, fin) for deb, fin in d["periodes"]):
                continue
            code, gid = s["votes"].get(d["id"], (0, None))
            if code == 4:
                continue  # non-votant réglementaire (présidence de séance…) : ni pénalisé, ni compté
            for st in (d["st"][k], d["st"][-1]):
                st["el"] += 1
                if code in (1, 2, 3):
                    st["vo"] += 1
                    if gid and gid not in ni and pos.get(gid) in (1, 2, 3):
                        st["alN"] += 1
                        if code == pos.get(gid):
                            st["al"] += 1
    for d in deputes:
        for st in d["st"]:
            st["part"] = round(st["vo"] / st["el"], 4) if st["el"] else None
            st["align"] = round(st["al"] / st["alN"], 4) if st["alN"] else None
    for k in range(len(periodes) + 1):
        seuil = SEUIL_TOTAL if k == len(periodes) else SEUIL_PERIODE
        ok = [d for d in actifs if d["st"][k]["el"] >= seuil]
        for cle in ("part", "align"):
            triees = sorted(d["st"][k][cle] for d in ok if d["st"][k][cle] is not None)
            for d in actifs:
                st = d["st"][k]
                st["p_" + cle] = rang_centile(st[cle], triees) if st["el"] >= seuil else None
    medianes = []
    for k in range(len(periodes) + 1):
        seuil = SEUIL_TOTAL if k == len(periodes) else SEUIL_PERIODE
        ok = [d for d in actifs if d["st"][k]["el"] >= seuil]
        medianes.append({c: mediane([d["st"][k][c] for d in ok]) for c in ("part", "align")})

    # statistiques par groupe
    for g in groupes:
        rice = [abs(b[3] - b[4]) / (b[3] + b[4]) for s in scrutins for b in s["groupes"] if b[0] == g["id"] and b[3] + b[4] > 0]
        g["rice"] = None if g["ni"] or not rice else round(sum(rice) / len(rice), 4)
        membres = [d for d in actifs if groupe_actuel.get(d["id"]) == g["id"]]
        g["partMed"] = mediane([d["st"][-1]["part"] for d in membres if d["st"][-1]["el"] >= SEUIL_TOTAL])
        partis = {}
        for d in membres:
            partis[d["parti"] or "Sans rattachement déclaré"] = partis.get(d["parti"] or "Sans rattachement déclaré", 0) + 1
        g["partis"] = sorted(partis.items(), key=lambda x: -x[1])
    positions = [{b[0]: b[2] for b in s["groupes"]} for s in scrutins]
    for g in groupes:
        g["accord"] = {}
        for h in groupes:
            if g["ni"] or h["ni"] or g is h:
                continue
            n = a = 0
            for pos in positions:
                x, y = pos.get(g["id"]), pos.get(h["id"])
                if x in (1, 2, 3) and y in (1, 2, 3):
                    n += 1
                    a += x == y
            g["accord"][h["id"]] = round(a / n, 4) if n >= SEUIL_TOTAL else None

    # compactage des votes : un caractère par député et par scrutin
    # 0 absent, 1 pour, 2 contre, 3 abstention, 4 non-votant, - hors mandat
    sortie_scrutins = []
    for s in scrutins:
        v = []
        for d in deputes:
            code = s["votes"].get(d["id"], (None, None))[0]
            if code:
                v.append(str(code))
            else:
                v.append("0" if any(dans(s["d"], deb, fin) for deb, fin in d["periodes"]) else "-")
        sortie_scrutins.append({"n": s["n"], "d": s["d"], "t": s["t"], "tl": s["tl"], "ti": s["ti"], "so": s["so"], "dm": s["dm"],
                                "vo": s["vo"], "ex": s["ex"], "rq": s["rq"], "po": s["po"], "co": s["co"], "ab": s["ab"], "nv": s["nv"],
                                "g": [[gindex.get(b[0], -1)] + b[1:] for b in s["groupes"]],
                                "m": [[index[r], c] for r, c in s["mises"] if r in index], "v": "".join(v)})

    donnees = {
        "maj": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "legislature": LEG,
        "sources": {"scrutins": URL_SCRUTINS, "acteurs": URL_ACTEURS, "licence": "Licence Ouverte / Open Licence (Etalab)"},
        "periodes": periodes, "medianes": medianes,
        "groupes": groupes,
        "deputes": [{"id": d["id"], "civ": d["civ"], "prenom": d["prenom"], "nom": d["nom"], "dept": d["dept"], "numDept": d["numDept"],
                     "circ": d["circ"], "actif": d["actif"], "debut": d["debut"], "periodes": d["periodes"],
                     "groupe": gindex.get(groupe_actuel.get(d["id"]) or (d["groupes"][-1][0] if d["groupes"] else ""), -1),
                     "hist": [[gindex.get(g, -1), deb, fin] for g, deb, fin in d["groupes"]],
                     "parti": d["parti"], "commission": d["commission"], "hatvp": d["hatvp"], "st": d["st"]} for d in deputes],
        "scrutins": sortie_scrutins,
    }
    verifier_contenus({s["n"] for s in scrutins}, {d["id"] for d in deputes})
    os.makedirs(os.path.dirname(SORTIE), exist_ok=True)
    with open(SORTIE, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Écrit : {SORTIE} ({os.path.getsize(SORTIE)/1e6:.1f} Mo)")
    print("Groupes : " + ", ".join(f"{g['sigle']} {g['effectif']}" for g in groupes if g["actif"]))

if __name__ == "__main__":
    construire()
