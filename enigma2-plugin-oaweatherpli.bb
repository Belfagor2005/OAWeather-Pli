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

do_install() {
    install -d ${D}${libdir}/enigma2/python/Plugins/Extensions/OAWeather
    cp -r ${S}/usr/lib/enigma2/python/Plugins/Extensions/OAWeather/* \
          ${D}${libdir}/enigma2/python/Plugins/Extensions/OAWeather/
}

FILES:${PN} = "${libdir}/enigma2/python/Plugins/Extensions/OAWeather"