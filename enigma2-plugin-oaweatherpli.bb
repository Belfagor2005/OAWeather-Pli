DESCRIPTION = "OAWeather-Pli"
MAINTAINER = "OEalliance"
SECTION = "base"
PRIORITY = "required"
LICENSE = "CLOSED"

require conf/license/license-gplv2.inc

inherit gitpkgv allarch

SRCREV = "${AUTOREV}"
PV = "4.7+git${SRCPV}"
PKGV = "4.7+git${GITPKGV}"
PR = "r0"

SRC_URI = "git://github.com/Belfagor2005/OAWeather-Pli.git;protocol=https;branch=main"

S = "${WORKDIR}/git"

FILES:${PN} = " \
    ${libdir}/enigma2/python/Plugins/Extensions/OAWeather/* \
    ${libdir}/enigma2/python/Components/Converter/OAWeather.py \
    ${libdir}/enigma2/python/Components/Renderer/* \
    ${libdir}/enigma2/python/Components/Sources/* \
    ${libdir}/enigma2/python/Tools/* \
"

do_install() {
    install -d ${D}${libdir}/enigma2/python/Plugins/Extensions/OAWeather
    cp -r ${S}/usr/lib/enigma2/python/Plugins/Extensions/OAWeather/* \
          ${D}${libdir}/enigma2/python/Plugins/Extensions/OAWeather/
    
    install -d ${D}${libdir}/enigma2/python/Components/Converter
    cp -r ${S}/usr/lib/enigma2/python/Components/Converter/OAWeather.py \
          ${D}${libdir}/enigma2/python/Components/Converter/
    
    install -d ${D}${libdir}/enigma2/python/Components/Renderer
    cp -r ${S}/usr/lib/enigma2/python/Components/Renderer/* \
          ${D}${libdir}/enigma2/python/Components/Renderer/
    
    install -d ${D}${libdir}/enigma2/python/Components/Sources
    cp -r ${S}/usr/lib/enigma2/python/Components/Sources/* \
          ${D}${libdir}/enigma2/python/Components/Sources/
    
    install -d ${D}${libdir}/enigma2/python/Tools
    cp -r ${S}/usr/lib/enigma2/python/Tools/* \
          ${D}${libdir}/enigma2/python/Tools/
}