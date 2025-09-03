resource "tailscale_acl" "acl" {
  acl = <<EOF
{
	// Declare static groups of users. Use autogroups for all users or users with a specific role.
	// "groups": {
	//      "group:example": ["alice@example.com", "bob@example.com"],
	// },

	// Define the tags which can be applied to devices and by which users.
	"tagOwners": {
		"tag:admin-device":  [],
		"tag:member-device": [],
		"tag:k8s-operator":  [],
		"tag:k8s":           ["tag:k8s-operator"],
		"tag:mullvad":       ["tag:admin-device"],
	},

	// Define access control lists for users, groups, autogroups, tags,
	// Tailscale IP addresses, and subnet ranges.
	"acls": [
		{
			"action": "accept",
			"src":    ["tag:member-device"],
			"dst":    ["tag:mullvad:*"],
		},
		{
			"action": "accept",
			"src":    ["autogroup:admin", "tag:admin-device", "tag:k8s", "tag:k8s-operator"],
			"dst":    ["*:*"],
		},
	],

	// Define users and devices that can use Tailscale SSH.
	"ssh": [
		// Allow all users to SSH into their own devices in check mode.
		// Comment this section out if you want to define specific restrictions.
		{
			"action": "check",
			"src":    ["autogroup:member"],
			"dst":    ["autogroup:self"],
			"users":  ["autogroup:nonroot", "root"],
		},
		{
			"action": "accept",
			"src":    ["autogroup:member"],
			"dst":    ["tag:k8s"],
			"users":  ["tag:admin-device", "autogroup:nonroot", "myoung"],
		},
	],
	"nodeAttrs": [
		{
			"target": ["*"],
			"app": {
				"tailscale.com/app-connectors": [],
			},
		},
		{
			"target": ["tag:k8s"],
			"attr":   ["funnel"],
		},
    // work laptop
		{"target": ["100.125.107.125"], "attr": ["mullvad"]},
    // home desktop
		{"target": ["100.69.116.77"], "attr": ["mullvad"]},
    // phone
		{"target": ["100.112.88.4"], "attr": ["mullvad"]},
	],
}
  EOF
}
