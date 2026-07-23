//
// CodeCache.cpp
//
// Library: OSP
// Package: Util
// Module:  CodeCache
//
// Copyright (c) 2007-2014, Applied Informatics Software Engineering GmbH.
// All rights reserved.
//
// SPDX-License-Identifier: GPL-3.0-only
//


#include "Poco/OSP/CodeCache.h"
#include "Poco/File.h"
#include "Poco/DirectoryIterator.h"
#include "Poco/FileStream.h"
#include "Poco/SharedLibrary.h"
#include "Poco/StreamCopier.h"
#include "Poco/SHA1Engine.h"


using Poco::File;
using Poco::SharedLibrary;
using Poco::StreamCopier;
using Poco::Timestamp;


namespace Poco {
namespace OSP {


CodeCache::CodeCache(const std::string& path, bool shared):
	_path(path)
{
	if (shared) _pMutex = new Poco::NamedMutex(mutexName(path));
	_path.makeDirectory();
	File dir(path);
	dir.createDirectories();
}


CodeCache::~CodeCache()
{
}


bool CodeCache::hasLibrary(const std::string& name)
{
	Path p(_path, name);
	File f(p);
	return f.exists();
}


Poco::Timestamp CodeCache::libraryTimestamp(const std::string& name)
{
	Path p(_path, name);
	File f(p);
	return f.getLastModified();
}


void CodeCache::installLibrary(const std::string& name, std::istream& istr)
{
	Path p(_path, name);
	File f(p);
	Poco::FileOutputStream ostr(f.path());
	if (ostr.good())
	{
		StreamCopier::copyStream(istr, ostr);
		ostr.close();
		f.setExecutable();
	}
	else throw CreateFileException(f.path());
}


void CodeCache::uninstallLibrary(const std::string& name)
{
	Path p(_path, name);
	File f(p);
	f.remove();
}


std::string CodeCache::pathFor(const std::string& name, bool appendSuffix)
{
	Path p(_path);
	if (!name.empty())
	{
		const std::string fileName = appendSuffix ? name + SharedLibrary::suffix() : name;
		p.setFileName(fileName);
		if (!appendSuffix)
		{
			return p.toString();
		}

		File f(p);
		if (!f.exists())
		{
			const std::string extension = p.getExtension();
			int bestScore = 0;
			Poco::Timestamp bestTimestamp;
			std::string bestPath;
			bool found = false;
			Poco::DirectoryIterator end;
			for (Poco::DirectoryIterator it(_path); it != end; ++it)
			{
				if (!it->isFile()) continue;
				Poco::Path candidatePath(it.path());
				const std::string candidateBaseName = candidatePath.getBaseName();
				if (!extension.empty() && candidatePath.getExtension() != extension) continue;

				int candidateScore = -1;
#if defined(_DEBUG)
				if (candidateBaseName == name + "d")
					candidateScore = 0;
				else if (candidateBaseName == name + "md")
					candidateScore = 1;
				else if (candidateBaseName == name)
					candidateScore = 2;
#else
				if (candidateBaseName == name + "md")
					candidateScore = 0;
				else if (candidateBaseName == name)
					candidateScore = 1;
				else if (candidateBaseName == name + "d")
					candidateScore = 2;
#endif
				if (candidateScore < 0) continue;

				const Poco::Timestamp candidateTimestamp = it->getLastModified();
				if (!found || candidateScore < bestScore || (candidateScore == bestScore && bestTimestamp < candidateTimestamp))
				{
					bestScore = candidateScore;
					bestTimestamp = candidateTimestamp;
					bestPath = it.path().toString();
					found = true;
				}
			}
			if (found) return bestPath;
		}
	}
	return p.toString();
}


void CodeCache::clear()
{
	File dir(_path);
	dir.remove(true);
	dir.createDirectories();
}


void CodeCache::lock()
{
	if (_pMutex) _pMutex->lock();
}


void CodeCache::unlock()
{
	if (_pMutex) _pMutex->unlock();
}


std::string CodeCache::mutexName(const std::string& path)
{
	std::string name("ospcc");
	Poco::Path p(path);
	p.makeAbsolute();
	p.makeDirectory();
	Poco::SHA1Engine sha1;
	sha1.update(p.toString());
	std::string hash = Poco::DigestEngine::digestToHex(sha1.digest());
	hash.resize(16);
	name += hash;
	return name;
}


} } // namespace Poco::OSP
