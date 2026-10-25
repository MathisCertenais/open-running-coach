# Third-party notices

This project bundles the following third-party libraries in
`app/static/vendor/`. They are redistributed unmodified under their own
licenses; the AGPL-3.0 license of this project does not override them.

## Leaflet 1.9.4

- File: `app/static/vendor/leaflet/`
- Copyright (c) 2010-2023 Vladimir Agafonkin, (c) 2010-2011 CloudMade
- License: BSD 2-Clause "Simplified" License
- Source: <https://github.com/Leaflet/Leaflet>

```
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Leaflet.heat / simpleheat

- File: `app/static/vendor/leaflet-heat/leaflet-heat.js`
- Copyright (c) 2014, Vladimir Agafonkin
- License: MIT (simpleheat), MIT (leaflet.heat)
- Source: <https://github.com/Leaflet/Leaflet.heat>,
  <https://github.com/mourner/simpleheat>

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Map tiles and external services

Map tiles are fetched at runtime from **OpenStreetMap** and remain subject to
the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
and to [OpenStreetMap's copyright and license](https://www.openstreetmap.org/copyright)
(ODbL for the data). No map data is bundled with this repository.

## Python dependencies

- **FastAPI** — MIT
- **Uvicorn** — BSD 3-Clause
- **Starlette** (pulled in by FastAPI) — BSD 3-Clause
- **Pydantic** (pulled in by FastAPI) — MIT

See `requirements.txt` for the versions this project was tested against.

## Fonts and icons

The interface uses system fonts only and inline Unicode/emoji glyphs; no font
files or icon sets are bundled.
