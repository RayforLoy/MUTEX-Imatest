# Third-party notices

Application: GPL-3.0-or-later; see LICENSE. Libraries retain their individual licenses.

Installed-distribution notices, versions and upstream project URLs: licenses/inventory.json
and licenses/ subdirectories. Exact environment: requirements-lock.txt.

PySide6/Qt dynamic libraries retain their applicable open-source GPL/LGPL terms. The
portable package permits replacement of dynamic libraries and does not restrict debugging
or reverse engineering needed to modify those libraries.

rawpy is the wrapper; actual LibRaw is the official 0.22.2 Windows release, selected under
LGPL terms. Official LGPL/CDDL/copyright texts: licenses/LibRaw-0.22.2. The original official
source/binary ZIP is included in Release archives under third-party-source/.
For a Git checkout, scripts/upgrade_libraw.py downloads the same official archive
into vendor/libraw-0.22.2 and records the URL, hash and DLL symbol verification in
validation/libraw-upgrade.json. LibRaw source was not modified; only its wheel DLL filename.

libvips retains LGPL-2.1-or-later; pyvips/pyvips-binary and bundled libraries retain their
upstream notices. NumPy, SciPy, OpenCV, Pillow, imagecodecs, Colour Science, msgpack,
platformdirs and other dependencies retain their own licenses.

cryptography provides Scrypt and AES-GCM for encrypted template packages under its
Apache-2.0 / BSD-3-Clause terms. Its bundled native components and their notices are
retained in licenses/cryptography/. Exact installed license texts and versions
are listed in licenses/inventory.json.

Synthetic chart/icon assets are CC0. The independent private asset packer and private chart
sources are excluded from the public software source and portable package.

The public template/ library has separate artwork licenses: original mathematical charts
are CC0 1.0; Leonhard Wimmer's Siemens star and Setreset / Mikhail Ryazanov's USAF chart,
including the documented derivative artwork, are CC BY-SA 3.0. Preserve template/ATTRIBUTION.md
and template/licenses/ when redistributing these assets. The application GPL does not replace
their artwork licenses. Source URLs, original upstream bytes, modifications and checksums
are included in template/.

No proprietary Imatest implementation, licensed chart original, ISO standard text or
certification is bundled.

Release-only template/bundled/ .mxasset files contain authorised user-supplied
measurement geometry and raster references. Original private SVG/PDF artwork is
excluded. This artwork remains proprietary; the application GPL does not grant
an open-source artwork licence. See template/bundled/README.txt. The public
template loader token permits offline use and is not a secrecy or DRM boundary.
