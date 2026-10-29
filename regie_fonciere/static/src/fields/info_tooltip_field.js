import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { Component, useProps } from "@odoo/owl";

/**
 * Info icon showing the value of a text field (e.g. the explanation of a rent amount) as a
 * tooltip on hover.
 */
export class InfoTooltipField extends Component {
    static template = "regie_fonciere.InfoTooltipField";
    props = useProps({ ...standardFieldProps });

    get value() {
        return this.props.record.data[this.props.name] || "";
    }
}

export const infoTooltipField = {
    component: InfoTooltipField,
    displayName: _t("Info Tooltip"),
    supportedTypes: ["char", "text"],
};

registry.category("fields").add("regie_info_tooltip", infoTooltipField);
