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
import re
import shutil
import zc.buildout

_isurl = re.compile('([a-zA-Z0-9+.-]+)://').match

# based on Zope2.utilities.mkzopeinstance.write_inituser
def Zope2InitUser(path, username, password):
  open(path, 'w').write('')
  os.chmod(path, 0600)
  open(path, "w").write('%s:{SHA}%s\n' % (
    username,binascii.b2a_base64(hashlib.sha1(password).digest())[:-1]))

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

    self.bt5_repository_list = []
    append = self.bt5_repository_list.append
    for repository in self.options.get('bt5-repository-list', '').split():
      repository = repository.strip()
      if not repository:
        continue

      if repository[:7] == 'file://':
        repository = repository[7:]
      elif _isurl(repository):
        # XXX: assume it's a valid URL
        append(repository)
        continue

      # XXX: it is invalid to apply os.path methods on an URL.
      #      Hint: urllib.url2pathname
      if os.path.isabs(repository):
        repo_id = hashlib.sha1(repository).hexdigest()
        link = os.path.join(repository_path, repo_id)
        if os.path.lexists(link):
          if not os.path.islink(link):
            raise zc.buildout.UserError(
              'Target link already %r exists but it is not link' % link)
          os.unlink(link)
        os.symlink(repository, link)
        self.logger.debug('Created link %r -> %r', link, repository_path)
        # Always provide a URL-Type
        append("file://" + link)

    # Generate Zeo connections
    zeo_snippet_template = open(self.getTemplateFilename('zope.zeo.entry.conf.in'
      )).read()
    zeo_snippet_list = []
    for zeo_line in self.options['zeo-connection-string'].splitlines():
      zeo_line.strip()
      if not zeo_line:
        continue
      d = dict()
      for param in zeo_line.split():
        k, v = param.split('=')
        d[k.strip()] = v.strip()
      zeo_snippet_list.append(zeo_snippet_template % d)
    # Create zope configuration file
    zope_config = dict(
        products=self.options['products'],
        thread_amount=self.options['thread-amount'],
        zodb_configuration='\n'.join(zeo_snippet_list)
    )
    zope_environment = dict(
      TMP=self.options['tmp-path'],
      TMPDIR=self.options['tmp-path'],
      HOME=self.options['tmp-path'],
      PATH=self.options['bin-path'],
      TIMEZONE=self.options['timezone'],
    )

    # longrequestlogger product which requires environment settings
    longrequest_logger_file = self.options.get('longrequest-logger-file', None)
    longrequest_logger_timeout = \
      self.options.get('longrequest-logger-timeout', None)
    longrequest_logger_interval= \
      self.options.get('longrequest-logger-interval', None)
    if longrequest_logger_file:
      # add needed zope configuration
      zope_environment.update(
        **dict(longrequestlogger_file = longrequest_logger_file,
               longrequestlogger_timeout = longrequest_logger_timeout,
               longrequestlogger_interval = longrequest_logger_interval))

    # configure default Zope2 zcml
    # XXX: shouldn't self.options['site-zcml'] be returned, as we created this
    # file ?
    shutil.copy(self.getTemplateFilename('site.zcml'),
      self.options['site-zcml'])
    zope_config['instance'] = self.options['instance-path']
    zope_config['event_log'] = self.options['event-log']
    zope_config['z2_log'] = self.options['z2-log']
    zope_config['pid-filename'] = self.options['pid-file']
    zope_config['lock-filename'] = self.options['lock-file']
    prefixed_products = []
    for product in reversed(zope_config['products'].split()):
      product = product.strip()
      if product:
        prefixed_products.append('products %s' % product)
    prefixed_products.insert(0, 'products %s' % self.options[
      'instance-products'])
    zope_config['products'] = '\n'.join(prefixed_products)
    zope_config['address'] = '%s:%s' % (self.options['ip'], self.options['port'])
    zope_config.update(dump_url=self.options['deadlock-path'],
      secret=self.options['deadlock-password'])

    zope_wrapper_template_location = self.getTemplateFilename('zope.conf.in')
    zope_conf_content = self.substituteTemplate(zope_wrapper_template_location,
      zope_config)
    if self.isTrueValue(self.options['timeserver']):
      zope_conf_content += self.substituteTemplate(self.getTemplateFilename(
          'zope.conf.timeserver.in'), {})

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
