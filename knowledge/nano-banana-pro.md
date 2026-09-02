# Nano Banana Pro (Gemini 3 Pro Image) — Référence prompting

> Cerveau de l'agent `banana-prompt-agent`. Mise à jour : 2026-06-16.
> Règle d'or absolue : on DÉCRIT une scène en langage naturel narratif, jamais une liste de mots-clés style Midjourney.

## 1. Capacités du modèle et réglages

| Capacité | Détail | Implication prompt |
|---|---|---|
| Modèle | Gemini 3 Pro Image, "thinking model" (planifie avant de générer) | Tolère des prompts longs et structurés |
| Résolution | 1K, 2K, 4K natif (K majuscule : `2K`, pas `2k`) | Recommander 2K par défaut, 4K pour impression/hero |
| Ratios supportés (Pro) | 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9 | Choisir selon l'emplacement (hero 16:9, schéma 4:3, social 9:16/4:5) |
| Texte dans l'image | Typo de pointe, multilingue, lisible | Texte entre guillemets + police nommée + position |
| Images de référence | Jusqu'à ~14 (6 objets + 5 personnages côté API Pro) | Expliciter le rôle de chaque référence |
| Cohérence personnages | Jusqu'à 5 personnes | Fournir des refs nommées |
| Grounding | Connexion Google Search (données factuelles) | Utile infographies ; vérifier l'exactitude |
| Thinking level | `minimal` (défaut) / `high` | `high` pour composition complexe, texte dense, infographie |
| Traçabilité | Watermark SynthID + C2PA sur chaque image | Signaler au client si pertinent |

Réglages AI Studio à recommander séparément (l'app Gemini ne les expose pas) :
résolution, ratio, thinking level.

## 2. Gabarit de prompt — 12 composants ordonnés

Composer un paragraphe cohérent (2-6 phrases en standard), pas une liste. Ordre :

1. **Verbe d'opération** — "Create an image of…", "Generate…", "Transform…", "Replace…"
2. **Sujet + matière/texture** — spécifique : "navy blue tweed suit" pas "suit"
3. **Action / pose** — "posing with a confident statuesque stance, slightly turned"
4. **Environnement / lieu** — "a sun-drenched minimalist living room"
5. **Composition / cadrage** — "extreme close-up", "wide shot", "low-angle", "center-framed", "aerial", "isometric"
6. **Caméra / objectif / focus** — voir taxonomie optique §4
7. **Éclairage** — "three-point softbox", "golden hour backlighting", "chiaroscuro, high contrast", "soft diffused light", "rim lighting"
8. **Couleurs / color grading / film stock** — "muted teal tones", "1980s color film, slightly grainy" ; pour la marque, citer les hex
9. **Style / esthétique** — "photorealistic", "3D render", "film noir", "watercolor", "editorial fashion magazine"
10. **Texte dans l'image** — entre guillemets + police + position : `The headline "URBAN EXPLORER" in bold white sans-serif at the top`
11. **Format / ratio / résolution** — "A 9:16 vertical poster", "cinematic 21:9", 2K/4K
12. **Rôle des références** (multi-image) — "Using the attached sketch as structure and the fabric sample as texture…"

## 3. Règles d'or (do's & don'ts spécifiques au modèle)

À FAIRE :
- Narration en phrases complètes, pas de mots-clés empilés.
- **Cadrage positif** : décrire ce qu'on veut, pas ce qu'on ne veut pas. "empty street" plutôt que "no cars". Reformuler toute exclusion en formulation positive.
- Décrire le hors-champ utile ("no other objects on the table" reste acceptable comme cadrage de composition).
- Matière et texture précises plutôt que catégorie générique.
- Texte entre guillemets, police nommée, position dans le cadre. Pour du texte complexe : faire valider le texte exact d'abord (méthode text-first), puis générer.
- `thinking level: high` pour compositions complexes / infographies / texte dense.
- Itérer en conversation plutôt que viser le prompt parfait du premier coup.

À ÉVITER :
- Prompts négatifs classiques ("no…", "without…") → reformuler en positif.
- Syntaxe Midjourney (`--ar`, tags virgulés).
- Compter sur le rendu parfait du petit texte (limitation connue, fautes possibles en multilingue).
- Considérer un diagramme factuel comme fiable sans vérification humaine.

## 4. Taxonomie optique (pour spécialité photo) — portée de open-generative-ai/promptUtils.js

### Caméras (label → description prompt)
- Modular 8K Digital → modular 8K digital cinema camera
- Full-Frame Cine Digital → full-frame digital cinema camera
- Grand Format 70mm Film → grand format 70mm film camera
- Studio Digital S35 → Super 35 studio digital camera
- Classic 16mm Film → classic 16mm film camera
- Premium Large Format Digital → premium large-format digital cinema camera

### Objectifs (label → description prompt)
- Creative Tilt Lens → creative tilt lens effect
- Compact Anamorphic → compact anamorphic lens
- Extreme Macro → extreme macro lens
- 70s Cinema Prime → 1970s cinema prime lens
- Classic Anamorphic → classic anamorphic lens
- Premium Modern Prime → premium modern prime lens
- Warm Cinema Prime → warm-toned cinema prime lens
- Swirl Bokeh Portrait → swirl bokeh portrait lens
- Vintage Prime → vintage prime lens
- Halation Diffusion → halation diffusion filter
- Clinical Sharp Prime → ultra-sharp clinical prime lens

### Focale → perspective
- 8mm → ultra-wide perspective
- 14mm → wide-angle perspective
- 24mm → wide-angle dynamic perspective
- 35mm → natural cinematic perspective
- 50mm → standard portrait perspective
- 85mm → classic portrait perspective

### Ouverture → profondeur de champ
- f/1.4 → shallow depth of field, creamy bokeh
- f/4 → balanced depth of field
- f/11 → deep focus clarity, sharp foreground to background

### Ordre d'assemblage photo (de référence, à adapter en narration)
sujet → "shot on a {caméra}" → "using a {objectif} at {focale}mm ({perspective})" → "aperture {ouverture}" → effet DoF → éclairage → "natural color science" → "high dynamic range" → tags qualité

## 5. Taxonomies complémentaires

### Banques de tags (ENHANCE_TAGS — boosters optionnels, à fondre dans la narration)
- Qualité : professional photography, ultra-detailed, 8K resolution, high dynamic range, award-winning
- Éclairage : cinematic lighting, golden hour, dramatic studio lighting, soft diffused light, neon glow, volumetric rays
- Ambiance : moody atmosphere, serene and peaceful, epic and dramatic, warm and cozy, dark and mysterious
- Style : photorealistic, oil painting, watercolor, digital art, concept art, anime, cyberpunk

### Recettes express par cas (QUICK_PROMPTS — bases d'une ligne à enrichir)
- Portrait : Professional portrait photograph, shallow depth of field, soft studio lighting, 85mm lens
- Landscape : Breathtaking landscape photograph, golden hour, wide angle, dramatic clouds, 4K
- Product : Commercial product photography, clean white background, studio lighting, professional
- Fantasy : Epic fantasy scene, magical atmosphere, volumetric lighting, highly detailed, concept art
- Sci-Fi : Futuristic sci-fi environment, neon lights, cyberpunk city, rain reflections, cinematic
- Food : Professional food photography, appetizing, warm lighting, shallow depth of field, editorial
- Architecture : Architectural photography, dramatic angles, clean lines, modern design, professional
- Fashion : High fashion editorial, avant-garde styling, studio lighting, Vogue aesthetic, professional

### Composition / cadrage
règle des tiers, leading lines, symmetrical, center-framed, negative space, close-up / medium / wide / extreme wide, low-angle / high-angle / eye-level / aerial / isometric / Dutch angle.

### Styles / esthétiques (liste de référence à enrichir)
photorealistic, 3D render, flat vector, editorial illustration, medical/scientific illustration, watercolor, oil painting, film noir, cinematic, fashion editorial, product studio, lifestyle, retro/vintage film.

### Palettes
toujours préférer les codes hex de la charte client quand un client est identifié (voir registre brand-sources.md).

## 6. Recettes par spécialité

Chaque recette = squelette de prompt + vocabulaire clé + réglages par défaut + pièges.

### 6.1 Illustration médicale / éditoriale
- Squelette : "Clean modern medical illustration, {ratio}, textbook quality. A {vue: cross-section/diagram} of {structure} clearly showing {éléments}. Smooth vector-style with subtle depth, {hex outlines}, {hex tissue tones}, {hex accents} on {élément clé}, clean white background, soft even lighting, scientifically accurate and educational."
- Vocabulaire : cross-section, transversal/vertical section, vector-style, textbook quality, anatomically accurate, flat clinical palette.
- Réglages défaut : ratio 4:3 (schéma) ou 16:9 (clinique), 2K, thinking high.
- Exclusions (en positif) : viser "clean white background" plutôt que "no background" ; pas de labels parasites (texte géré en HTML).
- Pièges : vérifier l'exactitude anatomique (le modèle peut halluciner) ; petit texte peu fiable.

### 6.2 Photo produit e-commerce
- Squelette : utilise la taxonomie optique §4. "Commercial product photography of {produit + matière} on {fond}, {éclairage studio}, shot on a {caméra} using a {objectif} at {focale}mm, aperture {ouverture}, {DoF}, natural color science, high dynamic range, professional."
- Vocabulaire : packshot, seamless backdrop, softbox, rim light, reflection, floating product, lifestyle context.
- Réglages défaut : ratio 1:1 ou 4:5 (fiche/feed), 2K (4K si zoom), thinking minimal/high selon complexité.
- Pièges : éviter le look plastique sursaturé stock-photo ; respecter le packaging réel si référence fournie.

### 6.3 Hero / web design
- Squelette : visuel conceptuel de marque avec espace négatif pour le texte HTML par-dessus. "Editorial {style} hero image, {ratio}, {sujet conceptuel}, {palette charte hex}, generous empty negative space on the {left/right} for overlaid text, {éclairage}, premium brand aesthetic."
- Vocabulaire : negative space, conceptual, brand-consistent, hero banner, depth, ambient.
- Réglages défaut : ratio 16:9 ou 21:9, 4K, thinking high.
- Pièges : respecter strictement la charte DESIGN.md ; prévoir la zone de texte ; pas de texte dans l'image sauf demande.

### 6.4 Créa pub / social
- Squelette : "{format} ad creative, {ratio}, {sujet + accroche}. The headline \"{texte}\" in {police} at {position}. {palette charte}, {style}, strong focal point, scroll-stopping."
- Vocabulaire : scroll-stopping, focal point, safe zone, headline, CTA, platform-native.
- Réglages défaut : ratio 9:16 (story/reel), 4:5 (feed), 1:1 ; 2K ; thinking high si texte.
- Pièges : respecter les safe zones plateforme ; texte court et lisible ; cohérence charte.
