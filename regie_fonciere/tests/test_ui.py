from odoo.tests import HttpCase, tagged

from .common import RegieTestCommon

CHECK_TOOLTIP_JS = """
(async () => {
    for (let i = 0; i < 100; i++) {
        const icon = document.querySelector('.o_regie_info_tooltip');
        if (icon) {
            if (icon.dataset.tooltip && icon.dataset.tooltip.includes('800')) {
                console.log('test successful');
            } else {
                console.error('the info icon has no explanation: ' + icon.dataset.tooltip);
            }
            return;
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    console.error('the info icon of the current rent was not found');
})();
"""


@tagged('post_install', '-at_install')
class TestUi(RegieTestCommon, HttpCase):

    def test_rent_explanation_tooltip(self):
        lease = self._create_lease()
        self.browser_js(
            '/odoo/action-regie_fonciere.regie_lease_action/%s' % lease.id,
            CHECK_TOOLTIP_JS,
            login=self.env.user.login,
        )
