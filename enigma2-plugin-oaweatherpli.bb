DESCRIPTION = "OAWeather-Pli"
MAINTAINER = "OEalliance"
SECTION = "base"
PRIORITY = "required"
LICENSE = "proprietary"

require conf/license/license-gplv2.inc

inherit gitpkgv allarch


SRCREV = "${AUTOREV}"
PV = "1.2+git${SRCPV}"
PKGV = "1.2+git${GITPKGV}"
VER ="3.5"
PR = "r0"

SRC_URI = "git://github.com/Belfagor2005/OAWeather-Pli.git;protocol=https;branch=main"

FILES_${PN} = "/usr/*"

S = "${WORKDIR}/git"

do_compile() {
}

do_install() {
	install -d ${D}/usr
	cp -af --no-preserve=ownership --preserve=mode,links ${S}/usr/* ${D}/usr/
	chmod -R a+rX ${D}/usr
}
