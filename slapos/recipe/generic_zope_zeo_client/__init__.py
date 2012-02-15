##############################################################################
#
# Copyright (c) 2011 Vifib SARL and Contributors. All Rights Reserved.
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsibility of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# guarantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
##############################################################################
from slapos.recipe.librecipe import GenericBaseRecipe
import binascii
import hashlib
import os
import shutil
import urllib
import zc.buildout

# based on Zope2.utilities.mkzopeinstance.write_inituser
def Zope2InitUser(path, username, password):
  umask = os.umask(0077)
  try:
    # XXX: Why not using safer SSHA ?
    open(path, 'w').write('%s:{SHA}%s\n' % (
      username, binascii.b2a_base64(hashlib.sha1(password).digest())[:-1]))
  finally:
    os.umask(umask)

class Recipe(GenericBaseRecipe):
  def _options(self, options):
    options['password'] = self.generatePassword()
    options['deadlock-password'] = self.generatePassword()

  def install(self):
    """
    All zope have to share file created by portal_classes
    (until everything is integrated into the ZODB).
    So, do not request zope instance and create multiple in the same partition.
    """
    Zope2InitUser(self.options['inituser'], self.options['user'],
      self.options['password'])

    # Symlink to BT5 repositories defined in instance config.
    # Those paths will eventually end up in the ZODB, and having symlinks
    # inside the XXX makes it possible to reuse such ZODB with another software
    # release[ version].
    # Note: this path cannot be used for development, it's really just a
    # read-only repository.
    repository_path = self.options['bt5-repository']

    for repository in self.options.get('bt5-repository-list', '').split():
      repository = repository.strip()
      if not repository:
        continue
      scheme, path = urllib.splittype(repository)
      if scheme is None:
        # Assume it's a native path.
        pass
      elif scheme == 'file':
        path = urllib.url2pathname(urllib.splithost(path)[1])
      else:
        # Nothing to do for non-local schemes
        continue
      if os.path.isabs(path):
        link = os.path.join(repository_path,
          hashlib.sha1(path).hexdigest())
        if os.path.lexists(link):
          if not os.path.islink(link):
            raise zc.buildout.UserError(
              'Target link already %r exists but it is not link' % link)
          os.unlink(link)
        os.symlink(path, link)
        self.logger.debug('Created link %r -> %r', link, repository_path)
    # Create zope configuration file
    zope_environment = {
      'TMP': self.options['tmp-path'],
      'TMPDIR': self.options['tmp-path'],
      'HOME': self.options['tmp-path'],
      'PATH': self.options['bin-path'],
      'TZ': self.options['timezone'],
    }
    # longrequestlogger product which requires environment settings
    longrequest_logger_file = self.options.get('longrequest-logger-file')
    if longrequest_logger_file:
      # add needed zope configuration
      zope_environment.update(
        longrequestlogger_file=longrequest_logger_file,
        longrequestlogger_timeout=self.options.get(
          'longrequest-logger-timeout'),
        longrequestlogger_interval=self.options.get(
          'longrequest-logger-interval'),
      )
    # configure default Zope2 zcml
    # XXX: shouldn't self.options['site-zcml'] be returned, as we created this
    # file ?
    shutil.copy(self.getTemplateFilename('site.zcml'),
      self.options['site-zcml'])
    prefixed_products = ['products ' + x.strip()
      for x in reversed(self.options['products'].split()) if x.strip()]
    prefixed_products.insert(0, 'products %s' % self.options[
      'instance-products'])
    zeo_snippet_template = open(self.getTemplateFilename('zope.zeo.entry.conf.in'
      )).read()
    zope_conf_content = self.substituteTemplate(self.getTemplateFilename('zope.conf.in'), {
      'thread_amount': self.options['thread-amount'],
      # XXX: why use ad-hoc parsing when there is json ?
      'zodb_configuration': '\n'.join(
        zeo_snippet_template % dict((y.strip() for y in x.split('=', 1))
          for x in zeo_line.split())
        for zeo_line in self.options['zeo-connection-string'].splitlines()
      ),
      'instance': self.options['instance-path'],
      'event_log': self.options['event-log'],
      'z2_log': self.options['z2-log'],
      'pid-filename': self.options['pid-file'],
      'lock-filename': self.options['lock-file'],
      'address': '%s:%s' % (self.options['ip'], self.options['port']),
      'dump_url': self.options['deadlock-path'],
      'secret': self.options['deadlock-password'],
      'products': '\n'.join(prefixed_products),
    })
    if self.isTrueValue(self.options['timeserver']):
      zope_conf_content += self.substituteTemplate(self.getTemplateFilename(
          'zope.conf.timeserver.in'), {})
    if 'tidstorage-ip' in self.options:
      zope_conf_content += self.substituteTemplate(self.getTemplateFilename(
          'zope.conf.tidstorage.in'), {
            'tidstorage-ip': self.options['tidstorage-ip'],
            'tidstorage-port': self.options['tidstorage-port'],
            })

    zope_conf_path = self.createFile(self.options['configuration-file'], zope_conf_content)
    return [
      zope_conf_path,
      self.createPythonScript(self.options['wrapper'],
        'slapos.recipe.librecipe.execute.executee', [
          [self.options['runzope-binary'].strip(), '-C', zope_conf_path],
          zope_environment,
        ]
      )
    ]
