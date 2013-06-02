"""
Tools for converting old- to new-style metadata.
"""

from collections import defaultdict
from .pkginfo import read_pkg_info

import re
import os
import textwrap
import pkg_resources

METADATA_VERSION = "2.0"

PLURAL_FIELDS = { "classifier" : "classifiers", 
                  "provides_dist" : "provides",
                  "provides_extra" : "extras" }

SKIP_FIELDS = set()

CONTACT_FIELDS = (({"email":"author_email", "name": "author"}, 
                    "author"),
                  ({"email":"maintainer_email", "name": "maintainer"}, 
                    "maintainer"))

# commonly filled out as "UNKNOWN" by distutils:
UNKNOWN_FIELDS = set(("author", "author_email", "platform", "home_page", 
                      "license"))

# Will only support markers-as-extras here. Wheel itself is probably
# the only program that uses non-extras markers in METADATA/PKG-INFO.
EXTRA_RE = re.compile("extra == '(?P<extra>.+)'")
KEYWORDS_RE = re.compile("[\0-,]+")

def unique(iterable):
    seen = set()
    for value in iterable:
        if not value in seen:
            seen.add(value)
            yield value

def pkginfo_to_dict(path, distribution=None):
    """
    Convert PKG-INFO to a prototype Metadata 2.0 dict.
    
    path: path to PKG-INFO file
    distribution: optional distutils Distribution()
    """
    
    metadata = {}
    pkg_info = read_pkg_info(path)
    
    if pkg_info['Description']:
        metadata['description'] = dedent_description(pkg_info)
        del pkg_info['Description']
    else:
        payload = pkg_info.get_payload()
        if payload:
            metadata['description'] = payload
    
    for key in unique(k.lower() for k in pkg_info.keys()):
        low_key = key.replace('-', '_')

        if low_key in SKIP_FIELDS: 
            continue
        
        if low_key in UNKNOWN_FIELDS and pkg_info.get(key) == 'UNKNOWN':
            continue

        if low_key in PLURAL_FIELDS:
            metadata[PLURAL_FIELDS[low_key]] = pkg_info.get_all(key)

        elif low_key == "requires_dist":
            requirements = []
            extra_requirements = defaultdict(list)
            for requirement, sep, marker in (value.partition(';') 
                                        for value in pkg_info.get_all(key)):
                marker = marker.strip()
                if marker:
                    extra_match = EXTRA_RE.match(marker)
                    if extra_match:
                        extra_name = extra_match.group('extra')
                        extra_requirements[extra_name].append(requirement)
                else:
                    requirements.append(requirement)
            metadata['requires'] = requirements
            if extra_requirements:
                metadata['may_require'] = [{'extra':key, 'dependencies':value} 
                        for key, value in sorted(extra_requirements.items())]
                if not 'extras' in metadata:
                    metadata['extras'] = []
                metadata['extras'].extend([key for key in sorted(extra_requirements.keys())])

        elif low_key == 'provides_extra':
            if not 'extras' in metadata:
                metadata['extras'] = []
            metadata['extras'].extend(pkg_info.get_all(key))

        elif low_key == 'home_page':
            metadata['project_urls'] = {'Home':pkg_info[key]}

        else:
            metadata[low_key] = pkg_info[key]

    metadata['metadata_version'] = METADATA_VERSION
    
    metadata['extras'] = sorted(unique(metadata['extras']))
    
    # include more information if distribution is available
    if distribution:
        for requires, attr in (('test_requires', 'tests_require'),):
            try:
                requirements = getattr(distribution, attr)
                if requirements:
                    metadata[requires] = requirements 
            except AttributeError:
                pass
            
    # handle contacts
    contacts = []
    for contact_type, role in CONTACT_FIELDS:
        contact = {}
        for key in contact_type:
            if contact_type[key] in metadata:
                contact[key] = metadata.pop(contact_type[key])
        if contact:
            contact['role'] = role
            contacts.append(contact)
    if contacts:
        metadata['contacts'] = contacts
        
    return metadata


def requires_to_requires_dist(requirement):
    """Compose the version predicates for requirement in PEP 345 fashion."""
    requires_dist = []
    for op, ver in requirement.specs:
        requires_dist.append(op + ver)
    if not requires_dist:
        return ''
    return " (%s)" % ','.join(requires_dist)


def pkginfo_to_metadata(egg_info_path, pkginfo_path):
    """
    Convert .egg-info directory with PKG-INFO to the Metadata 1.3 aka
    old-draft Metadata 2.0 format.
    """
    pkg_info = read_pkg_info(pkginfo_path)
    pkg_info.replace_header('Metadata-Version', '2.0')
    requires_path = os.path.join(egg_info_path, 'requires.txt')
    if os.path.exists(requires_path):
        requires = open(requires_path).read()
        for extra, reqs in pkg_resources.split_sections(requires):
            condition = ''
            if extra:
                pkg_info['Provides-Extra'] = extra
                condition = '; extra == %s' % repr(extra)
            for req in reqs:
                parsed_requirement = pkg_resources.Requirement.parse(req)
                spec = requires_to_requires_dist(parsed_requirement)
                extras = ",".join(parsed_requirement.extras)
                if extras:
                    extras = "[%s]" % extras 
                pkg_info['Requires-Dist'] = (parsed_requirement.project_name 
                                             + extras 
                                             + spec 
                                             + condition)

    description = pkg_info['Description']
    if description:
        pkg_info.set_payload(dedent_description(pkg_info))
        del pkg_info['Description']

    return pkg_info


def dedent_description(pkg_info):
    """
    Dedent and convert pkg_info['Description'] to Unicode.
    """
    description = pkg_info['Description']
    
    # Python 3 Unicode handling, sorta.
    surrogates = False
    if not isinstance(description, str):
        surrogates = True
        for item in pkg_info.raw_items():
            if item[0].lower() == 'description':
                description = item[1].encode('ascii', 'surrogateescape')\
                                             .decode('utf-8')
                break

    description_lines = description.splitlines()
    description_dedent = '\n'.join(
            # if the first line of long_description is blank,
            # the first line here will be indented.
            (description_lines[0].lstrip(),
             textwrap.dedent('\n'.join(description_lines[1:])),
             '\n'))

    if surrogates:
        description_dedent = description_dedent\
                .encode("utf8")\
                .decode("ascii", "surrogateescape")
                
    return description_dedent


if __name__ == "__main__":
    import sys, pprint
    pprint.pprint(pkginfo_to_dict(sys.argv[1]))