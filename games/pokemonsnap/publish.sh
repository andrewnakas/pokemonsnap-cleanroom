#!/bin/sh
# Publish sources (main) and the web build (gh-pages) to andrewnakas/pokemonsnap-cleanroom.
#   sh games/pokemonsnap/publish.sh      (only after taint_report prints 0 failing for clean/snap.z64)
set -e
R="$(cd "$(dirname "$0")/../.." && pwd)"
W=D:/n64work/pokemonsnap
grep -q " 0 failing" $W/taint_final.log || { echo "refusing: taint_final.log does not say 0 failing"; exit 1; }
[ $W/taint_final.log -nt $W/clean/snap.z64 ] || { echo "refusing: taint log older than the ROM"; exit 1; }
cd "$R"
gh repo view andrewnakas/pokemonsnap-cleanroom >/dev/null 2>&1 || gh repo create andrewnakas/pokemonsnap-cleanroom --public \
  --description "Pokemon Snap in the browser, built from the pokemonsnap decomp with every ROM asset regenerated (clean room)"
git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/andrewnakas/pokemonsnap-cleanroom.git
git push -q origin main
S=$W/site_pub
rm -rf $S
python ports/emu/make_site.py $S $W/clean/snap.z64
cd $S
git init -q -b gh-pages
git add -A
git -c user.name=andre -c user.email=treesixtyweather@gmail.com commit -qm "Web build

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git remote add origin https://github.com/andrewnakas/pokemonsnap-cleanroom.git
git push -q -f origin gh-pages
gh api -X POST repos/andrewnakas/pokemonsnap-cleanroom/pages -f "source[branch]=gh-pages" -f "source[path]=/" >/dev/null 2>&1 || true
gh api repos/andrewnakas/pokemonsnap-cleanroom/pages --jq '.html_url + " " + .status'
