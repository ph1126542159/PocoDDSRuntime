//
// BundleLifecycleGuard.h
//
// Library: OSP
// Package: Bundle
// Module:  BundleLifecycleGuard
//

#ifndef OSP_BundleLifecycleGuard_INCLUDED
#define OSP_BundleLifecycleGuard_INCLUDED


#include "Poco/OSP/OSP.h"
#include "Poco/OSP/Service.h"
#include <string>
#include <typeinfo>
#include <vector>


namespace Poco {
namespace OSP {


struct OSP_API BundleLifecycleDecision
{
	bool allowed = true;
	std::string code;
	std::string detail;
	std::vector<std::string> affectedBundles;
};


class OSP_API BundleLifecycleGuard: public Service
	/// A policy extension point consulted by BundleLoader before a Bundle is
	/// started or stopped. Multiple implementations can register unique service
	/// names with the "pdr.lifecycle.guard" property; all are evaluated in
	/// deterministic service-name order. A single implementation registered
	/// under SERVICE_NAME without that property remains supported.
{
public:
	using Ptr = Poco::AutoPtr<BundleLifecycleGuard>;
	static constexpr const char* SERVICE_NAME = "osp.bundleLifecycleGuard";

	virtual BundleLifecycleDecision evaluateStart(
		const std::string& symbolicName) const = 0;
		/// Returns whether the named Bundle may be started.

	virtual BundleLifecycleDecision evaluateStop(
		const std::string& symbolicName) const = 0;
		/// Returns whether the named Bundle may be stopped.

	const std::type_info& type() const override
	{
		return typeid(BundleLifecycleGuard);
	}

	bool isA(const std::type_info& otherType) const override
	{
		return std::string(otherType.name()) ==
			typeid(BundleLifecycleGuard).name() || Service::isA(otherType);
	}

protected:
	~BundleLifecycleGuard() override = default;
};


} } // namespace Poco::OSP


#endif // OSP_BundleLifecycleGuard_INCLUDED
