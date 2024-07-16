#!/usr/bin/env python3
import json
import os
import subprocess
import xml.etree.ElementTree as xml
from datetime import datetime
from urllib.parse import urlsplit
import markdown
from markdown import Extension
from markdown.treeprocessors import Treeprocessor

REPOSITORY = 'kjarosh/ruffle'


def get_filename_from_url(url=None):
    if url is None:
        return None
    urlpath = urlsplit(url).path
    return os.path.basename(urlpath)


class SanitizeTreeprocessor(Treeprocessor):
    def __init__(self, md=None):
        super().__init__(md)

        self.allowed_tags = {'p', 'li', 'ul', 'ol', 'em', 'code'}
        self.tag_mapping = {
            'strong': 'em',
        }

    def run(self, root):
        self.sanitize(root, None, 0)

    def sanitize(self, element, parent, idx):
        for idx, child in enumerate(element):
            self.sanitize(child, element, idx)

        if element.tag in self.tag_mapping.keys():
            element.tag = self.tag_mapping.get(element.tag)

        if parent is not None and element.tag not in self.allowed_tags:
            if idx == 0:
                parent.text += self.to_text(element)
            else:
                parent[idx - 1].tail += self.to_text(element)
            parent.remove(element)

    def to_text(self, element):
        result = element.text
        for child in element:
            result += self.to_text(child)
        result += element.tail
        return result


class SanitizeExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(SanitizeTreeprocessor(md), 'sanitize', 0)


def generate_metainfo_description(description):
    md = markdown.markdown(description, extensions=[SanitizeExtension()])
    description_html = '<description>' + md + '</description>'
    return xml.ElementTree(xml.fromstring(description_html)).getroot()


def generate_metainfo_artifacts(tag_name, json_release):
    xml_artifacts = xml.Element('artifacts')

    xml_artifact = xml.Element('artifact')

    xml_location = xml.Element('location')
    xml_location.text = f'https://github.com/{REPOSITORY}/archive/refs/tags/{tag_name}.zip'

    xml_filename = xml.Element('filename')
    xml_filename.text = f'ruffle-{tag_name}.zip'

    xml_artifact.set('type', 'source')
    xml_artifact.append(xml_location)
    xml_artifact.append(xml_filename)
    xml_artifacts.append(xml_artifact)

    for asset in json_release['assets']:
        filename = os.path.basename(urlsplit(asset['url']).path)
        print(f'  Artifact: {filename}')

        if filename.endswith('-linux-x86_64.tar.gz'):
            artifact_type = 'binary'
            platform = 'x86_64-linux-gnu'
        elif filename.endswith('-windows-x86_32.zip'):
            artifact_type = 'binary'
            platform = 'i386-windows-msvc'
        elif filename.endswith('-windows-x86_64.zip'):
            artifact_type = 'binary'
            platform = 'x86_64-windows-msvc'
        elif filename.endswith('-macos-universal.tar.gz'):
            artifact_type = 'binary'
            platform = 'any-macos-any'
        else:
            continue

        xml_artifact = xml.Element('artifact')

        xml_location = xml.Element('location')
        xml_location.text = asset['url']

        xml_filename = xml.Element('filename')
        xml_filename.text = filename

        xml_size = xml.Element('size')
        xml_size.set('type', 'download')
        xml_size.text = str(asset['size'])

        xml_artifact.set('type', artifact_type)
        xml_artifact.set('platform', platform)
        xml_artifact.append(xml_location)
        xml_artifact.append(xml_filename)
        xml_artifact.append(xml_size)
        xml_artifacts.append(xml_artifact)

    return xml_artifacts


def generate_metainfo_release(tag_name):
    print(f'Generating info for release {tag_name}')

    string_release = subprocess.run([
        'gh', 'release', 'view', tag_name,
        '--repo', REPOSITORY,
        '--json', 'assets,body,createdAt,isPrerelease,name,publishedAt,url',
    ], capture_output=True, text=True).stdout
    json_release = json.loads(string_release)

    version = tag_name.lstrip('v')
    date = datetime.fromisoformat(json_release['publishedAt']).strftime('%Y-%m-%d')
    url = json_release['url']
    release_type = 'snapshot' if json_release['isPrerelease'] else 'stable'

    print(f'  Version: {version}')
    print(f'  Date: {date}')
    print(f'  Type: {release_type}')
    print(f'  URL: {url}')
    print(f'  Artifact count: {len(json_release['assets'])}')

    xml_release = xml.Element('release')
    xml_release.set('version', version)
    xml_release.set('date', date)
    xml_release.set('type', release_type)

    xml_url = xml.Element('url')
    xml_url.text = url

    xml_description = generate_metainfo_description(json_release['body'])

    xml_artifacts = generate_metainfo_artifacts(tag_name, json_release)

    xml_release.append(xml_url)
    xml_release.append(xml_description)
    xml_release.append(xml_artifacts)
    return xml_release


def sync_metainfo_releases(metainfo_releases_path):
    xml_metainfo_releases = xml.parse(metainfo_releases_path)

    string_release_list = subprocess.run([
        'gh', 'release', 'list',
        '--repo', REPOSITORY,
        '--limit', '60',
        '--exclude-drafts',
        '--exclude-pre-releases',
        '--json', 'tagName',
    ], capture_output=True, text=True).stdout
    json_releases = json.loads(string_release_list)

    print(f'Releases to synchronize: {json_releases}')
    for json_release in reversed(json_releases):
        xml_release = generate_metainfo_release(json_release['tagName'])

        replaced = False
        for idx, existing_release in enumerate(xml_metainfo_releases.getroot()):
            if existing_release.get('version') == xml_release.get('version'):
                xml_metainfo_releases.getroot()[idx] = xml_release
                replaced = True
                break

        if not replaced:
            xml_metainfo_releases.getroot().insert(0, xml_release)

    xml.indent(xml_metainfo_releases, space="    ")
    xml_metainfo_releases.write(metainfo_releases_path, encoding='utf-8')
    with open(metainfo_releases_path, 'a') as fd:
        fd.write('\n')
    pass


def main():
    script_path = os.path.realpath(__file__)
    script_dir_path = os.path.dirname(script_path)
    repo_path = os.path.abspath(os.path.join(script_dir_path, '../../'))

    metainfo_releases_path = os.path.join(repo_path, 'rs.ruffle.Ruffle.releases.xml')

    print(f'Repository path: {repo_path}')
    print(f'Metainfo releases path: {metainfo_releases_path}')

    print(f'Syncing metainfo releases')
    sync_metainfo_releases(metainfo_releases_path)
    pass


if __name__ == '__main__':
    main()
