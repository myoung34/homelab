resource "tailscale_acl" "acl" {
  acl = <<EOF
  {
  	"tagOwners": {
  		"tag:k8s-operator": [],
  		"tag:k8s":          ["tag:k8s-operator"],
  	},

  	"acls": [
  		//Allow all connections.
  		//Comment this section out if you want to define specific restrictions.
  		{"action": "accept", "src": ["*"], "dst": ["*:*"]},
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
  			"users":  ["3vilpenguin@gmail.com", "autogroup:nonroot", "myoung"],
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
  		{"target": ["100.125.107.125"], "attr": ["mullvad"]},
  		{"target": ["100.69.116.77"], "attr": ["mullvad"]},
  		{"target": ["100.119.170.123"], "attr": ["mullvad"]},
  	],

  	// Test access rules every time they're saved.
  	// "tests": [
  	//  	{
  	//  		"src": "alice@example.com",
  	//  		"accept": ["tag:example"],
  	//  		"deny": ["100.101.102.103:443"],
  	//  	},
  	// ],
  }
  EOF
}
